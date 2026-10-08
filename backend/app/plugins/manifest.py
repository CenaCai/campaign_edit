"""插件 manifest 规范与校验。

一个插件包（.ceplugin 实际就是目录/zip）可同时提供：
  components   自定义内容块（渲染器 + props_schema）
  themes       主题 token 包
  templates    模板包
  intent_rules 意图词典扩展（往 lexicon 注入词条）
  mcp          MCP server 配置（把外部能力接进来）
  assets       静态资源（导出时复制）

安全立场：**manifest 只声明数据与渲染函数，不允许任意代码执行**。
渲染器白名单：内置 renderer 前缀 + 插件自带 ``render.py`` 中的显式函数名映射。
远程安装默认关闭（settings.plugin_allow_remote_install=False）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MANIFEST_NAME = "plugin.json"
ALLOWED_KINDS = {"component", "theme", "template", "intent_rule", "mcp", "bundle"}
COMPONENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*$")
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ASSET_BYTES = 8 * 1024 * 1024


class ManifestError(ValueError):
    pass


def empty_manifest(key: str = "my.plugin", name: str = "My Plugin",
                   version: str = "0.1.0", kind: str = "bundle") -> dict[str, Any]:
    return {
        "key": key, "name": name, "version": version, "kind": kind,
        "description": "", "author": "", "homepage": "",
        "min_app_version": "0.1.0",
        "permissions": [],
        "components": [], "themes": [], "templates": [],
        "intent_rules": [], "mcp": None,
        "assets": [],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    mf = path / MANIFEST_NAME
    if not mf.exists():
        raise ManifestError(f"缺少 {MANIFEST_NAME}")
    if mf.stat().st_size > MAX_MANIFEST_BYTES:
        raise ManifestError("manifest 过大")
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest JSON 非法: {exc}") from exc
    validate_manifest(data)
    return data


def validate_manifest(m: dict[str, Any]) -> None:
    if not isinstance(m, dict):
        raise ManifestError("manifest 必须是对象")
    for f in ("key", "name", "version", "kind"):
        if not m.get(f):
            raise ManifestError(f"manifest 缺少必填字段: {f}")
    if m["kind"] not in ALLOWED_KINDS:
        raise ManifestError(f"kind 必须是 {sorted(ALLOWED_KINDS)} 之一")
    if not re.match(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$", m["key"]):
        raise ManifestError("key 形如 csts.sports（必须带命名空间）")

    comps = m.get("components") or []
    if not isinstance(comps, list):
        raise ManifestError("components 必须是数组")
    for c in comps:
        if not isinstance(c, dict):
            raise ManifestError("components 每项必须是对象")
        if not COMPONENT_KEY_RE.match(str(c.get("key") or "")):
            raise ManifestError(
                f"组件 key 非法: {c.get('key')!r}（应形如 csts.ticket_card）")
        kinds = c.get("kind") or []
        if not isinstance(kinds, list) or not set(kinds) <= {"email", "form", "landing"}:
            raise ManifestError(f"组件 {c['key']} 的 kind 必须是 email/form/landing 子集")
        if not c.get("renderer"):
            raise ManifestError(f"组件 {c['key']} 缺少 renderer")
        allowed_r = c.get("renderer") in _SAFE_RENDERERS
        if not allowed_r:
            raise ManifestError(
                f"组件 {c['key']} 的 renderer={c.get('renderer')!r} 不在白名单。"
                f"允许：{sorted(_SAFE_RENDERERS)}"
            )

    for t in (m.get("templates") or []):
        if not isinstance(t, dict) or not t.get("kind"):
            raise ManifestError("templates 每项需含 kind")
        if t["kind"] not in ("email", "form", "landing"):
            raise ManifestError("template.kind 非法")

    ir = m.get("intent_rules") or []
    if not isinstance(ir, list):
        raise ManifestError("intent_rules 必须是数组")
    for r in ir:
        if not isinstance(r, dict) or not isinstance(r.get("direct"), dict):
            raise ManifestError("intent_rules 每项需形如 {direct:{email:[[词,权重]]}}")

    mcp = m.get("mcp")
    if mcp:
        if not isinstance(mcp, dict) or not mcp.get("command"):
            raise ManifestError("mcp 需含 command（stdio 型）")
        if mcp.get("transport", "stdio") == "http" and not mcp.get("url"):
            raise ManifestError("mcp http 传输需提供 url")


# 渲染器白名单：插件复用宿主已实现的渲染函数，不允许任意代码
_SAFE_RENDERERS = {
    "generic_section", "generic_spacer", "generic_text", "generic_image",
    "generic_button", "generic_html", "generic_field",
    "email_section", "email_spacer", "email_text", "email_image", "email_button",
    "email_footer", "email_social",
    "form_field_text", "form_field_email", "form_field_phone", "form_field_select",
    "form_field_number", "form_field_textarea",
    "landing_section", "landing_text", "landing_image", "landing_button",
    "landing_feature_grid", "landing_spacer", "landing_social_links",
}


def is_safe_renderer(name: str) -> bool:
    return name in _SAFE_RENDERERS


def plan_install(m: dict[str, Any]) -> dict[str, Any]:
    """由 manifest 计算"将要注册什么"，用于安装前确认页。"""
    return {
        "key": m["key"], "name": m["name"], "version": m["version"], "kind": m["kind"],
        "components": [{"key": c["key"], "name": c.get("name"), "kind": c.get("kind"),
                        "renderer": c.get("renderer")} for c in (m.get("components") or [])],
        "themes": [{"key": t.get("key"), "name": t.get("name")} for t in (m.get("themes") or [])],
        "templates": [{"key": t.get("key"), "name": t.get("name"), "kind": t.get("kind")}
                      for t in (m.get("templates") or [])],
        "intent_rule_groups": len(m.get("intent_rules") or []),
        "mcp": bool(m.get("mcp")),
        "permissions": m.get("permissions") or [],
        "assets": m.get("assets") or [],
    }


def write_scaffold(directory: str | Path, *, key: str = "acme.demo",
                   name: str = "ACME Demo", kind: str = "bundle") -> Path:
    """生成一个可运行的插件骨架（``python -m app.plugins.manifest scaffold <dir>``）。"""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    mf = empty_manifest(key=key, name=name, kind=kind)
    mf["description"] = "示例插件：注册一个组件 + 一个主题"
    mf["components"] = [{
        "key": "acme.banner", "name": "ACME 横幅", "kind": ["landing", "email"],
        "category": "hero", "container": False, "renderer": "generic_text",
        "props_schema": {
            "text": {"type": "string", "label": "文案", "default": "Hello ACME",
                     "required": True},
            "color": {"type": "string", "label": "文字色", "default": "#c8102e"},
            "font_size": {"type": "string", "label": "字号", "default": "28px"},
        },
        "style_defaults": {"font-weight": "800"},
        "example": {"text": "ACME 官方合作伙伴"},
    }]
    mf["themes"] = [{"key": "acme-brand", "name": "ACME 品牌", "kind_scope": "all",
                     "tokens": {"brand": "#0a5", "secondary": "#062"} }]
    mf["templates"] = [{
        "key": "acme_promo_landing", "name": "ACME 促销页", "kind": "landing",
        "scenario": "promo", "tags": ["促销", "acme"], "locale": "zh-CN",
        "description": "示例：hero + 特性网格 + CTA",
        "schema": {
            "kind": "landing",
            "doc": {"name": "ACME 促销活动", "subject": "", "preheader": "",
                    "locale": "zh-CN", "description": ""},
            "theme": {"theme_id": "acme-brand", "token_overrides": {}},
            "root": {"id": "root", "type": "landing.root", "props": {}, "style": {},
                     "children": [
                         {"id": "h1", "type": "landing.hero", "props": {
                             "layout": "centered", "min_height": "420px"},
                          "style": {"background_color": "#062"}, "children": [
                             {"id": "h1t", "type": "landing.heading", "props": {
                                 "text": "ACME 新品首发", "level": "h1",
                                 "color": "#ffffff", "align": "center"}},
                             {"id": "h1b", "type": "landing.button", "props": {
                                 "text": "立即抢购", "url": "https://example.com",
                                 "variant": "primary"}, "style": {}}]},
                         {"id": "s1", "type": "landing.section", "props": {},
                          "style": {}, "children": [
                             {"id": "f1", "type": "landing.feature_grid", "props": {
                                 "columns": 3, "items": [
                                     {"icon": "⚡", "title": "极速发货", "desc": "24h 内出库"},
                                     {"icon": "🔒", "label": "", "title": "正品保障",
                                      "desc": "官方授权"},
                                     {"icon": "🎧", "title": "无忧售后", "desc": "7天无理由"}]},
                              "style": {}}]},
                         {"id": "f2", "type": "landing.section", "props": {},
                          "style": {}, "children": [
                             {"id": "b1", "type": "acme.banner",
                              "props": {"text": "ACME 官方合作伙伴", "color": "#0a5"},
                              "style": {"text_align": "center", "padding": "32px"}}]}]},
        },
    }]
    mf["intent_rules"] = [{"direct": {"landing": [["acme活动", 2.4], ["acme新品", 2.0]]},
                           "scenario": {"promo": ["acme促销"]}}]
    (root / MANIFEST_NAME).write_text(json.dumps(mf, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    readme = f"""# {name}

Campaign Edit 插件包。

## 目录结构

```
plugin.json          # manifest：声明式，不含可执行代码
README.md
```

## 注册了什么

- 组件 `acme.banner`（复用宿主渲染器 `generic_text`）
- 主题 `acme-brand`
- 模板 `acme_promo_landing`
- 意图词典扩展：`acme活动` / `acme新品` → landing

## 安装

后台「插件中心」→「安装本地插件」，选择本目录；或

```bash
curl -X POST http://localhost:8000/api/v1/plugins/install \\
  -H 'Content-Type: application/json' \\
  -d '{{"path": "{key}"}}'
```

## 约定

1. 组件 `key` 必须带命名空间，避免与内置块冲突。
2. `renderer` 只能取白名单中的值；要自定义渲染逻辑，
   请在宿主 `backend/app/render/generic.py` 注册（代码评审后合并）。
3. `props_schema` 驱动编辑器的属性面板，请补齐 `label` 与 `default`。
"""
    (root / "README.md").write_text(readme, encoding="utf-8")
    return root