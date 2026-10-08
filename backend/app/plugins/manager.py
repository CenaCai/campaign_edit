"""插件管理器：安装 / 启用 / 停用 / 卸载 +运行时注册。

生命周期
--------
    scan()                扫描 plugin_dir，发现未登记的包
    install(dir|zip)      校验 manifest → 复制到 plugins/<key>/<version> → 注册 DB → 注册运行时
    enable/disable        切换 status；disable 时移除运行时注册（已用内容不受影响，
                          因为渲染前会做 _renderer 回填，且 schema 快照自带样式）
    uninstall(key)        软卸载：status=disabled + 移出运行时；不删目录（可回滚）

运行时注册 = 向blocks.registry / render.theme / intent.lexicon 注入。
卸载时必须能干净回滚，因此每处注入都记录来源（source_plugin）并可精确移除。
"""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..blocks.registry import get_registry
from ..config import settings
from ..models import Plugin, Template, Theme
from . import manifest as mf
from .mcp_client import MCPClient, MCPClientError


class PluginError(RuntimeError):
    pass


# ---------------------------------------------------------------- 安装

def install_from_dir(db: Session, src: Path, *, installed_by: str | None = None,
                     activate: bool = True) -> dict[str, Any]:
    src = Path(src).resolve()
    if not src.is_dir():
        raise PluginError(f"目录不存在: {src}")
    data = mf.load_manifest(src)

    key, version = data["key"], data["version"]
    target_root = Path(settings.plugin_dir) / key
    target = target_root / version
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, target)

    plan = mf.plan_install(data)
    installed = _upsert_record(db, data, plan, str(target), installed_by)
    if activate:
        applied = activate_plugin(db, installed)
    else:
        applied = {"activated": False, "reason": "activate=false"}

    installed.runtime_state = {**installed.runtime_state, "last_install": {
        "at": datetime.now(timezone.utc).isoformat(), "plan": plan}}
    db.commit()
    return {"plugin": plugin_dict(installed), "plan": plan, **applied}


def install_from_zip(db: Session, zip_path: str | Path, *,
                     installed_by: str | None = None) -> dict[str, Any]:
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise PluginError(f"压缩包不存在: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        raise PluginError("不是合法的 zip")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                # 防 zip-slip
                dest = (Path(tmp) / name).resolve()
                if not str(dest).startswith(str(Path(tmp).resolve())):
                    raise PluginError(f"压缩包含非法路径: {name}")
            z.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir() if p.is_dir()]
        if not (Path(tmp) / mf.MANIFEST_NAME).exists():
            if len(roots) != 1:
                raise PluginError("压缩包内未找到 plugin.json（或结构不唯一）")
            pkg = roots[0]
        else:
            pkg = Path(tmp)
        return install_from_dir(db, pkg, installed_by=installed_by)


def _upsert_record(db: Session, data: dict, plan: dict, path: str,
                   installed_by: str | None) -> Plugin:
    p = db.execute(select(Plugin).where(Plugin.key == data["key"])).scalar_one_or_none()
    if p is None:
        p = Plugin(key=data["key"], created_at=datetime.now(timezone.utc))
        db.add(p)
    p.name = data["name"]
    p.version = data["version"]
    p.kind = data["kind"]
    p.description = data.get("description", "")
    p.author = data.get("author", "")
    p.manifest = data
    p.install_path = path
    p.capabilities = [c["key"] for c in plan["components"]]
    p.permissions = plan["permissions"]
    p.installed_by = installed_by
    p.status = "active" if p.status in ("active", "") else p.status
    db.flush()
    return p


# ---------------------------------------------------------------- 运行时注册

def activate_plugin(db: Session, plugin: Plugin) -> dict[str, Any]:
    data = plugin.manifest or {}
    result: dict[str, Any] = {"activated": True, "components": [], "themes": [],
                              "templates": [], "intent_rules": 0, "mcp": None,
                              "errors": []}

    registry = get_registry()
    for comp in data.get("components") or []:
        try:
            spec = _comp_to_spec(comp, plugin.key)
            registry.register(spec, replace=True)
            result["components"].append(comp["key"])
        except Exception as exc:
            result["errors"].append(f"组件 {comp.get('key')} 注册失败: {exc}")

    for th in data.get("themes") or []:
        row = db.execute(select(Theme).where(Theme.key == th["key"])).scalar_one_or_none()
        if row is None:
            row = Theme(key=th["key"], name=th.get("name") or th["key"])
            db.add(row)
        row.name = th.get("name") or row.name
        row.kind_scope = th.get("kind_scope", "all")
        row.tokens = th.get("tokens", {})
        row.css_vars = {f"--{k}": v for k, v in (th.get("tokens") or {}).items()}
        row.is_builtin = False
        row.source_plugin = plugin.key
        result["themes"].append(th["key"])

    for tp in data.get("templates") or []:
        row = db.execute(select(Template).where(Template.key == tp["key"])).scalar_one_or_none()
        if row is None:
            row = Template(key=tp["key"], name=tp.get("name") or tp["key"], kind=tp["kind"])
            db.add(row)
        row.name = tp.get("name") or row.name
        row.kind = tp["kind"]
        row.scenario = tp.get("scenario", "generic")
        row.locale = tp.get("locale", "zh-CN")
        row.description = tp.get("description", "")
        row.tags = tp.get("tags", [])
        row.channel = tp.get("channel", "")
        row.schema = tp.get("schema", {})
        row.is_active = True
        row.source_plugin = plugin.key
        result["templates"].append(tp["key"])

    n = apply_intent_rules(data.get("intent_rules") or [], plugin.key)
    result["intent_rules"] = n

    if data.get("mcp"):
        try:
            client = MCPClient(data["mcp"])
            status = client.probe()
            result["mcp"] = {"name": data["mcp"].get("name", plugin.key), **status}
            if not status.get("ok"):
                result["errors"].append(f"MCP 探测失败: {status.get('error')}")
        except MCPClientError as exc:
            result["errors"].append(str(exc))
            result["mcp"] = {"ok": False, "error": str(exc)}

    plugin.status = "active"
    plugin.runtime_state = {**(plugin.runtime_state or {}), "applied": result}
    db.flush()
    return result


def _comp_to_spec(comp: dict, plugin_key: str) -> dict:
    if not mf.is_safe_renderer(comp.get("renderer")):
        raise PluginError(f"renderer {comp.get('renderer')!r} 不在白名单")
    return {
        "key": comp["key"], "name": comp.get("name") or comp["key"],
        "kind": comp.get("kind") or ["landing"],
        "category": comp.get("category", "plugin"),
        "container": bool(comp.get("container", False)),
        "renderer": comp["renderer"],
        "props_schema": comp.get("props_schema") or {},
        "style_defaults": comp.get("style_defaults") or {},
        "children_allowed": comp.get("children_allowed"),
        "children_limit": comp.get("children_limit"),
        "source": "plugin", "source_plugin": plugin_key,
        "example": comp.get("example"),
    }


def apply_intent_rules(rules: list[dict], plugin_key: str) -> int:
    """把插件词条并入运行时词典。"""
    from ..intent import lexicon
    count = 0
    for r in rules or []:
        direct = r.get("direct") or {}
        for kind, pairs in direct.items():
            if kind not in lexicon.DIRECT:
                continue
            for kw, w in pairs:
                lexicon.DIRECT[kind].append((str(kw), float(w)))
                count += 1
        for scen, words in (r.get("scenario") or {}).items():
            lexicon.SCENARIO.setdefault(scen, [])
            for w in words:
                lexicon.SCENARIO[scen].append(str(w))
                count += 1
        for kind, pairs in (r.get("action") or {}).items():
            for item in pairs:
                kw, w, bias = item[0], item[1], item[2]
                lexicon.ACTION.append((str(kw), float(w), bias))
                count += 1
    return count


def deactivate_plugin(db: Session, plugin: Plugin) -> dict[str, Any]:
    from ..intent import lexicon
    removed: dict[str, Any] = {"components": 0, "intent_rules": 0}
    registry = get_registry()
    for c in (plugin.manifest or {}).get("components") or []:
        spec = registry.get(c["key"])
        if spec and spec.get("source_plugin") == plugin.key:
            registry.unregister(c["key"])
            removed["components"] += 1
    removed["intent_rules"] = _revoke_intent_rules(plugin.manifest or {}, plugin.key)
    for t in db.execute(select(Template).where(Template.source_plugin == plugin.key)).scalars():
        t.is_active = False
    plugin.status = "disabled"
    db.flush()
    return removed


def _revoke_intent_rules(manifest: dict, plugin_key: str) -> int:
    """按插件注入的条目反查移除（词条带唯一值比对，足够精确）。"""
    from ..intent import lexicon
    n = 0
    for r in (manifest.get("intent_rules") or []):
        for kind, pairs in (r.get("direct") or {}).items():
            if kind in lexicon.DIRECT:
                before = len(lexicon.DIRECT[kind])
                lexicon.DIRECT[kind] = [x for x in lexicon.DIRECT[kind]
                                         if not any(x[0] == str(kw) and abs(x[1] - float(w)) < 1e-9
                                                    for kw, w in pairs)]
                n += before - len(lexicon.DIRECT[kind])
        for scen, words in (r.get("scenario") or {}).items():
            lst = lexicon.SCENARIO.get(scen)
            if lst:
                before = len(lst)
                lexicon.SCENARIO[scen] = [w for w in lst if w not in {str(x) for x in words}]
                n += before - len(lexicon.SCENARIO[scen])
    return n


def uninstall_plugin(db: Session, key: str, *, purge: bool = False) -> dict[str, Any]:
    p = db.execute(select(Plugin).where(Plugin.key == key)).scalar_one_or_none()
    if p is None:
        raise PluginError(f"插件未安装: {key}")
    removed = deactivate_plugin(db, p)
    p.status = "disabled"
    if purge and p.install_path:
        shutil.rmtree(Path(p.install_path).parent, ignore_errors=True)
    db.commit()
    return {"key": key, "purged": purge, **removed}


# ---------------------------------------------------------------- 同步 / 扫描

def sync_all(db: Session) -> dict[str, Any]:
    """启动时调用：把 DB 里status=active 的插件重新注册到运行时。"""
    out = {"activated": [], "errors": []}
    for p in db.execute(select(Plugin).where(Plugin.status == "active")).scalars():
        try:
            activate_plugin(db, p)
            out["activated"].append(p.key)
        except Exception as exc:
            p.status = "broken"
            out["errors"].append(f"{p.key}: {exc}")
    db.commit()
    return out


def scan(db: Session) -> list[dict[str, Any]]:
    """扫描 plugin_dir，找出已存在但未登记的包。"""
    root = Path(settings.plugin_dir)
    found: list[dict[str, Any]] = []
    if not root.exists():
        return found
    known = {p.key: p for p in db.execute(select(Plugin)).scalars()}
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        for ver_dir in sorted(child.iterdir()):
            if not (ver_dir / mf.MANIFEST_NAME).exists():
                continue
            try:
                data = mf.load_manifest(ver_dir)
            except mf.ManifestError as exc:
                found.append({"path": str(ver_dir), "ok": False, "error": str(exc)})
                continue
            rec = known.get(data["key"])
            found.append({
                "path": str(ver_dir), "ok": True, "key": data["key"],
                "name": data["name"], "version": data["version"],
                "installed": rec is not None,
                "installed_version": rec.version if rec else None,
                "status": rec.status if rec else None,
                "outdated": bool(rec and rec.version != data["version"]),
            })
    return found


def plugin_dict(p: Plugin) -> dict[str, Any]:
    return {
        "id": p.id, "key": p.key, "name": p.name, "version": p.version, "kind": p.kind,
        "description": p.description, "author": p.author, "status": p.status,
        "capabilities": p.capabilities or [], "permissions": p.permissions or [],
        "registry": p.runtime_state or {}, "install_path": p.install_path,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def load_builtin_demo_plugins() -> list[Path]:
    """首次启动时写入示例插件（plugins/acme.demo/）。"""
    root = Path(settings.plugin_dir) / "acme.demo"
    if root.exists():
        return []
    created = mf.write_scaffold(root, key="acme.demo", name="ACME Demo 插件",
                                kind="bundle")
    return [created]