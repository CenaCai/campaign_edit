"""Patch API：AI 局部修改。

三条路径：
  POST /contents/{id}/patch          结构化 operations（人或 AI 客户端调用）
  POST /contents/{id}/ai-patch      自然语言 → AI 翻译 → operations → 应用
  GET  /contents/{id}/outline       组件 id 清单（人和 AI 都用它定位）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...models import Content, User
from ...blocks.schema import schema_diff
from ...patch import ai as ai_mod          # 显式从 app.patch 导入，避免与本模块同名冲突
from ...patch.operations import OPS, PatchError, apply_operations, outline_index
from .services import ServiceError, save_content

router = APIRouter(tags=["patch"])


class Operation(BaseModel):
    op: str = Field(..., description=f"操作类型：{', '.join(OPS)}")
    target: str | None = Field(None, description="目标组件 id")
    prop: str | None = None
    style: str | None = None
    field: str | None = None
    token: str | None = None
    type: str | None = Field(None, description="add_block 的组件类型")
    parent_id: str | None = None
    index: int | None = None
    hidden: bool | None = None
    value: Any = None
    props: dict[str, Any] | None = None
    note: str | None = None


class PatchRequest(BaseModel):
    operations: list[Operation] = Field(..., min_length=1)
    message: str = ""
    dry_run: bool = False          # 只算 diff 不落库
    lint_gate: bool = True
    create_version: bool = True


class AiPatchRequest(BaseModel):
    instruction: str = Field(..., min_length=1, max_length=2000)
    dry_run: bool = True           # AI 默认先预览，人确认后再提交
    apply_operations: list[Operation] | None = None  # 用户确认后回传并提交
    message: str = ""


def _get(db: Session, cid: str) -> Content:
    c = db.get(Content, cid)
    if c is None:
        raise HTTPException(404, "内容不存在")
    return c


def _current_schema(db: Session, c: Content) -> dict:
    from ...models import ContentVersion
    if c.current_version_id:
        v = db.get(ContentVersion, c.current_version_id)
        if v:
            return v.schema
    from ...export.templates import empty_schema
    return empty_schema(c.kind, name=c.name, key=c.key)


@router.get("/patch/schema", summary="支持的操作与限制")
def patch_schema(user: User = Depends(get_current_user)) -> dict:
    return ai_mod.suggest_schema()


@router.get("/contents/{content_id}/outline", summary="组件清单（供人和 AI 定位）")
def outline(content_id: str, version: int | None = None,
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict:
    c = _get(db, content_id)
    schema = _current_schema(db, c)
    return {"content_id": c.id, "kind": c.kind,
            "root_id": (schema.get("root") or {}).get("id"),
            "blocks": outline_index(schema)}


@router.post("/contents/{content_id}/patch", summary="应用局部修改（结构化 operations）")
def patch(content_id: str, req: PatchRequest, db: Session = Depends(get_db),
          user: User = Depends(get_current_user)) -> dict[str, Any]:
    if not settings.patch_enabled:
        raise HTTPException(403, "Patch 功能已关闭（PATCH_ENABLED=false）")
    c = _get(db, content_id)
    schema = _current_schema(db, c)
    ops = [o.model_dump(exclude_none=True) for o in req.operations]

    try:
        result = apply_operations(schema, ops, dry_run=req.dry_run,
                                  max_ops=settings.patch_max_ops)
    except PatchError as exc:
        raise HTTPException(422, {"message": str(exc), "hint":
                                  "可先 GET .../outline 确认组件 id 与可用属性"}) from exc

    diff = schema_diff(schema, result.schema)
    payload: dict[str, Any] = {
        "content_id": c.id,
        "dry_run": req.dry_run,
        "ok": result.ok,
        "applied": result.applied,
        "diff": {"summary": diff["summary"], "count": len(diff["changes"])},
        "warnings": result.warnings,
    }

    if req.dry_run:
        payload["preview_schema"] = result.schema
        payload["message"] = f"预演完成：{len(result.applied)} 个操作，{len(diff['changes'])} 处改动。确认后可提交。"
        return payload

    try:
        saved = save_content(
            db, content=c, user=user, schema=result.schema,
            message=req.message or f"Patch 修改 {len(result.applied)} 处",
            create_version=req.create_version, lint_gate=req.lint_gate, force=True)
    except ServiceError as exc:
        raise HTTPException(exc.status_code,
                            {"message": exc.message, **exc.extra}) from exc

    payload["version"] = saved.current_version
    payload["message"] = f"已保存为 v{saved.current_version}（{len(result.applied)} 个操作）"
    return payload


@router.post("/contents/{content_id}/ai-patch", summary="自然语言改内容（AI 翻译为 operations）")
def ai_patch(content_id: str, req: AiPatchRequest, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> dict[str, Any]:
    if not settings.patch_enabled:
        raise HTTPException(403, "Patch 功能已关闭（PATCH_ENABLED=false）")
    c = _get(db, content_id)
    schema = _current_schema(db, c)

    # 路径 A：用户在前端确认过，直接提交回传的 operations（不重复调模型）
    if req.apply_operations is not None:
        ops = [o.model_dump(exclude_none=True) for o in req.apply_operations]
        return patch(content_id,
                     PatchRequest(operations=req.apply_operations,
                                  message=req.message or "AI 修改（已确认）",
                                  dry_run=False),
                     db, user)

    # 路径 B：AI 翻译
    if not settings.patch_ai_enabled:
        raise HTTPException(403, "AI 改写已关闭（PATCH_AI_ENABLED=false）")
    tr = ai_mod.translate(req.instruction, schema)
    if not tr.get("ok"):
        status = 503 if "LLM 未配置" in str(tr.get("error")) else 422
        raise HTTPException(status, {"message": tr.get("error"),
                                     "fallback": tr.get("fallback")})

    ops = tr["operations"]
    if not ops:
        return {"content_id": c.id, "ok": True, "operations": [],
                "message": tr.get("note") or "模型未生成操作，可能是指令不明确",
                "hint": "试试更具体的说法：'把 <组件名> 的标题改成 XXX'"}

    if not req.dry_run:
        raise HTTPException(400, {
            "message": "AI 改写默认先预览。确认无误后请回传 apply_operations。",
            "operations": ops, "note": tr.get("note")})

    try:
        result = apply_operations(schema, ops, dry_run=True,
                                  max_ops=settings.patch_max_ops)
    except PatchError as exc:
        raise HTTPException(422, {
            "message": f"AI 生成的操作无法应用：{exc}",
            "operations": ops,
            "hint": "可以直接修改这些 operations 后重试，或改用更明确的指令",
        }) from exc

    diff = schema_diff(schema, result.schema)
    return {
        "content_id": c.id, "ok": True, "instruction": req.instruction,
        "operations": ops, "applied": result.applied,
        "diff": {"summary": diff["summary"], "count": len(diff["changes"])},
        "note": tr.get("note"), "warnings": result.warnings,
        "preview_schema": result.schema,
        "message": f"AI 生成 {len(ops)} 个操作，将产生 {len(diff['changes'])} 处改动。"
                   f"确认后提交 apply_operations。",
    }


@router.get("/contents/{content_id}/ai-suggest", summary="AI 建议改进点（只读）")
def ai_suggest(content_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict[str, Any]:
    """基于 lint 与内容结构给出改进建议（不调LLM，纯规则，因此永远可用）。"""
    c = _get(db, content_id)
    schema = _current_schema(db, c)
    from ...render import preview as render_preview
    pv = render_preview(schema, kind=c.kind)
    from ...assets.service import validate_assets
    ac = validate_assets(db, schema)

    suggestions: list[dict[str, Any]] = []
    for issue in pv["lint"]["issues"]:
        suggestions.append({
            "kind": "lint", "severity": issue["severity"], "code": issue["code"],
            "message": issue["message"], "fix": issue.get("fix", ""),
            "node_id": issue.get("node_id", ""),
        })
    if ac["missing"]:
        suggestions.append({
            "kind": "asset", "severity": "error",
            "message": f"{len(ac['missing'])} 个图片资产缺失",
            "fix": "重新上传，或从组件里移除这些图片引用", "keys": ac["missing"],
        })
    if ac["no_alt"]:
        suggestions.append({
            "kind": "asset", "severity": "warn",
            "message": f"{len(ac['no_alt'])} 处图片缺少 alt",
            "fix": "补 alt（无障碍与 Gmail 图片策略）", "items": ac["no_alt"],
        })
    info = pv["info"]
    if info.get("text_chars", 0) < 80:
        suggestions.append({"kind": "content", "severity": "info",
                            "message": "正文内容偏少",
                            "fix": "补充关键信息：利益点、时间、地点、联系方式"})
    if c.kind == "landing" and info.get("link_count", 0) == 0:
        suggestions.append({"kind": "content", "severity": "warn",
                            "message": "页面没有任何链接",
                            "fix": "至少有一个明确的 CTA"})

    order = {"error": 0, "warn": 1, "info": 2}
    suggestions.sort(key=lambda s: order.get(s["severity"], 3))
    return {"content_id": c.id, "kind": c.kind,
            "score": pv["lint"]["score"], "count": len(suggestions),
            "suggestions": suggestions}