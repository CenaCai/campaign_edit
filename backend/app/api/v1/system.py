"""系统 API：健康检查、配置、token 定义、Mautic 状态。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...blocks.registry import get_registry
from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...models import Content, Plugin, Template, Theme, User
from ...render.theme import TOKEN_META, default_tokens

router = APIRouter(tags=["system"])


@router.get("/health", summary="健康检查（无需鉴权）")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        n_content = len(db.execute(select(Content)).scalars().all())
        db_ok = True
    except Exception as exc:
        n_content, db_ok = -1, False
        _ = exc
    return {"status": "ok" if db_ok else "degraded", "db": db_ok,
            "contents": n_content, "version": settings.app_version,
            "blocks": len(get_registry().list())}


@router.get("/config", summary="前端启动配置")
def public_config(db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...export import mautic as mautic_mod
    counts = {
        "email": db.execute(select(Template).where(Template.kind == "email")).scalars().all(),
        "form": db.execute(select(Template).where(Template.kind == "form")).scalars().all(),
        "landing": db.execute(select(Template).where(Template.kind == "landing")).scalars().all(),
    }
    return {
        "app": {"name": settings.app_name, "version": settings.app_version,
                "env": settings.env},
        "llm": {
            "enabled": settings.llm_enabled,
            "configured": settings.llm_configured,
            "model": settings.llm_model,
            "base_host": _host(settings.llm_base_url),
            "note": "未配置时意图识别自动降级为规则通道",
        },
        "mautic": mautic_mod.maulic_config_status(),
        "auth_disabled": settings.auth_disabled,
        "templates": {k: len(v) for k, v in counts.items()},
        "plugins": len(db.execute(select(Plugin).where(Plugin.status == "active")).scalars().all()),
        "themes": len(db.execute(select(Theme)).scalars().all()),
        "intent": {"min_confidence": settings.intent_min_confidence,
                   "auto_template_score": settings.intent_auto_template_score},
        "export_dir": settings.export_dir,
        "plugin_dir": settings.plugin_dir,
    }


def _host(url: str) -> str:
    if not url:
        return ""
    return url.split("//", 1)[-1].split("/", 1)[0]


@router.get("/tokens", summary="设计 token 定义")
def tokens(user: User = Depends(get_current_user)) -> dict[str, Any]:
    base = default_tokens()
    return {"tokens": {k: {"value": v, **TOKEN_META[k]} for k, v in base.items()}}


@router.get("/status-map", summary="状态机定义（前端渲染流转按钮用）")
def status_map(user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...models import ContentStatus
    return {
        "labels": ContentStatus.LABEL,
        "transitions": {k: list(v) for k, v in ContentStatus.TRANSITIONS.items()},
    }


@router.get("/health/deep", summary="深度健康检查（含外部依赖）")
def deep(user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...export import mautic as mautic_mod
    from ...plugins.mcp_client import MCPClient
    out: dict[str, Any] = {"llm": {}, "mautic": {}}
    if settings.llm_configured:
        try:
            import urllib.request
            url = settings.llm_base_url.rstrip("/") + "/models"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {settings.llm_api_key}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                out["llm"] = {"ok": r.status == 200, "status": r.status}
        except Exception as exc:
            out["llm"] = {"ok": False, "error": str(exc)[:200]}
    else:
        out["llm"] = {"ok": False, "reason": "not_configured"}
    if settings.mautic_configured:
        out["mautic"] = mautic_mod.MauticClient().ping()
    else:
        out["mautic"] = {"ok": False, "reason": "not_configured"}
    _ = MCPClient
    return out