"""插件 API + 组件注册表 API。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...blocks.registry import get_registry
from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...models import Plugin, User
from ...schemas import BlockOut, PluginInstallIn, PluginOut
from . import services

router = APIRouter(prefix="/plugins", tags=["plugins"])
block_router = APIRouter(prefix="/blocks", tags=["blocks"])


# ---------------------------------------------------------------- 组件

@block_router.get("", response_model=list[BlockOut], summary="可用组件（编辑器左栏）")
def list_blocks(kind: str | None = None, category: str | None = None,
                include_roots: bool = False,
                user: User = Depends(get_current_user)) -> list[dict]:
    return get_registry().as_api(kind)


@block_router.get("/categories")
def categories(kind: str = "email", user: User = Depends(get_current_user)) -> list[dict]:
    return get_registry().categories(kind)


@block_router.get("/{block_key}")
def block_detail(block_key: str, user: User = Depends(get_current_user)) -> dict:
    spec = get_registry().get(block_key)
    if spec is None:
        raise HTTPException(404, f"组件不存在: {block_key}")
    return dict(spec)


@block_router.post("/preview", summary="用示例 props 渲染单个组件")
def preview_block(payload: dict[str, Any], user: User = Depends(get_current_user)) -> dict:
    """单组件预览。优先走内容类型自己的渲染器（邮件表格布局等），
    插件组件（generic_* 渲染器）回退到通用渲染器。"""
    from ...render.generic import GenericRenderer
    from ...render import RENDERERS
    from ...blocks.schema import make_node
    key = payload.get("type")
    spec = get_registry().get(key)
    if spec is None:
        raise HTTPException(404, f"组件不存在: {key}")
    kind = (spec.get("kind") or ["landing"])[0]
    node = make_node(key, payload.get("props"), spec=dict(spec))
    node["style"] = payload.get("style") or {}
    node["_renderer"] = spec.get("renderer")

    html = ""
    renderer_cls = RENDERERS.get(kind)
    if renderer_cls is not None:
        r = renderer_cls()
        # 邮件渲染器是按整棵 schema 树渲染的，这里包一层单节点树
        fn = getattr(r, f"r_{key.replace('.', '_')}", None)
        if fn is not None:
            try:
                html = fn(node)
            except Exception as exc:  # 单组件渲染失败不应阻塞编辑器
                html = f"<!-- 渲染失败: {esc_html(exc)} -->"
        elif hasattr(r, "node"):
            html = r.node(node)
    if not html:
        html = GenericRenderer().node(node) or f"<!-- 组件 {key} 暂无可用渲染器 -->"
    return {"type": key, "kind": kind, "html": html}


def esc_html(v: Any) -> str:
    import html as _h
    return _h.escape(str(v))


# ---------------------------------------------------------------- 插件

@router.get("", response_model=list[PluginOut], summary="已安装插件")
def list_plugins(db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> list[PluginOut]:
    rows = db.execute(select(Plugin).order_by(Plugin.key)).scalars()
    return [PluginOut.from_plugin(p) for p in rows]


@router.get("/scan", summary="扫描本地插件目录（发现未登记的包）")
def scan(db: Session = Depends(get_db),
         user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...plugins.manager import scan as scan_plugins
    items = scan_plugins(db)
    return {"plugin_dir": settings.plugin_dir, "items": items,
            "remote_install_enabled": settings.plugin_allow_remote_install}


@router.get("/scaffold", summary="生成插件骨架到本地目录")
def scaffold(directory: str, key: str = "acme.demo", name: str = "ACME Demo",
             user: User = Depends(get_current_user)) -> dict:
    from ...plugins.manifest import write_scaffold
    path = write_scaffold(Path(directory), key=key, name=name)
    return {"directory": str(path), "manifest": str(path / "plugin.json"),
            "next": f"调用 /api/v1/plugins/install 传 path={path}"}


@router.post("/install", summary="安装插件（本地目录 / zip；远程需显式开启）")
def install(req: PluginInstallIn, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict:
    from ...plugins.manager import PluginError, install_from_dir, install_from_zip
    try:
        if req.zip_path:
            res = install_from_zip(db, Path(req.zip_path), installed_by=user.id)
        elif req.path:
            res = install_from_dir(db, Path(req.path), installed_by=user.id,
                                   activate=req.activate)
        elif req.url:
            if not settings.plugin_allow_remote_install:
                raise PluginError(
                    "远程安装默认关闭（PLUGIN_ALLOW_REMOTE_INSTALL=false）。"
                    "请把插件包放到本地后用 path 安装，或由管理员显式开启。")
            raise PluginError("当前版本未内置远程下载；请下载后用 path/zip_path 安装。")
        else:
            raise PluginError("必须提供 path、zip_path 或 url 之一")
    except PluginError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"安装失败: {exc}") from exc
    return res


@router.post("/{key}/activate", response_model=PluginOut, summary="启用并注册运行时")
def activate(key: str, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> PluginOut:
    from ...plugins.manager import PluginError, activate_plugin
    p = _get_plugin(db, key)
    try:
        activate_plugin(db, p)
    except PluginError as exc:
        raise HTTPException(400, str(exc)) from exc
    db.commit()
    db.refresh(p)
    return PluginOut.from_plugin(p)


@router.post("/{key}/disable", response_model=PluginOut, summary="停用（软下线，可回滚）")
def disable(key: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> PluginOut:
    from ...plugins.manager import deactivate_plugin
    p = _get_plugin(db, key)
    removed = deactivate_plugin(db, p)
    p.runtime_state = {**(p.runtime_state or {}), "last_disable": removed}
    db.commit()
    db.refresh(p)
    return PluginOut.from_plugin(p)


@router.delete("/{key}", summary="卸载（软卸载：仅 disable；purge=true 才删目录）")
def uninstall(key: str, purge: bool = False, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> dict:
    from ...plugins.manager import PluginError, uninstall_plugin
    try:
        return uninstall_plugin(db, key, purge=purge)
    except PluginError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/mcp/servers", summary="插件提供的 MCP servers")
def mcp_servers(db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> list[dict]:
    out = []
    for p in db.execute(select(Plugin)).scalars():
        m = (p.manifest or {}).get("mcp")
        if m:
            out.append({"plugin": p.key, "status": p.status,
                        "probe": (p.runtime_state or {}).get("applied", {}).get("mcp"),
                        "config": {"name": m.get("name"), "transport": m.get("transport", "stdio"),
                                   "command": m.get("command"), "args": m.get("args"),
                                   "url": m.get("url")}})
    return out


@router.post("/mcp/probe", summary="探测 MCP server（连通性 + 工具清单）")
def mcp_probe(payload: dict[str, Any], user: User = Depends(get_current_user)) -> dict:
    from ...plugins.mcp_client import MCPClient
    cfg = payload.get("config") or {}
    if not cfg.get("command") and not cfg.get("url"):
        raise HTTPException(400, "config 需含 command(stdio) 或 url(http)")
    return MCPClient(cfg).probe()


@router.post("/mcp/call", summary="调用 MCP 工具（谨慎：会触达外部系统）")
def mcp_call(payload: dict[str, Any], user: User = Depends(get_current_user)) -> dict:
    from ...plugins.mcp_client import MCPClient, MCPClientError
    cfg = payload.get("config") or {}
    tool = payload.get("tool")
    if not tool:
        raise HTTPException(400, "缺少 tool")
    client = MCPClient(cfg)
    try:
        client.initialize()
        res = client.call_tool(tool, payload.get("arguments") or {},
                               timeout=payload.get("timeout"))
        return {"ok": True, "result": res}
    except MCPClientError as exc:
        raise HTTPException(502, str(exc)) from exc
    finally:
        client.close()


def _get_plugin(db: Session, key: str) -> Plugin:
    p = db.execute(select(Plugin).where(Plugin.key == key)).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, f"插件未安装: {key}")
    return p