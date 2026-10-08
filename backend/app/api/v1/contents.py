"""内容 API：CRUD、版本、预览、审核、协作、导出入口。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ...blocks.registry import get_registry
from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...export import exporter
from ...export import mautic as mautic_mod
from ...export.templates import empty_schema, instantiate, next_key, validate_schema
from ...models import (Comment, Content, ContentKind, ContentStatus, ContentVersion,
                       ExportJob, ReviewTask, Template, Theme, User)
from ...render import preview as render_preview, resolve_tokens, extract_info
from ...schemas import (CommentIn, CommentOut, ContentCreate, ContentOut, ContentSave,
                        ContentUpdate, ExportOut, ExportRequest, LockIn, ReviewIn,
                        ReviewOut, TemplateOut, ThemeOut, VersionOut)
from . import services

router = APIRouter(prefix="/contents", tags=["contents"])


def _err(exc: services.ServiceError) -> HTTPException:
    return HTTPException(exc.status_code, {"message": exc.message, **exc.extra})


def _get_content(db: Session, content_id: str) -> Content:
    c = db.get(Content, content_id)
    if c is None:
        raise HTTPException(404, "内容不存在")
    return c


# ---------------------------------------------------------------- 列表/详情

@router.get("", response_model=list[ContentOut], summary="内容列表")
def list_contents(
    kind: str | None = None, status: str | None = None, project_id: str | None = None,
    q: str | None = None, mine: bool = False,
    limit: int = Query(50, le=200), offset: int = 0,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
) -> list[Content]:
    stmt = select(Content)
    if kind:
        stmt = stmt.where(Content.kind == kind)
    if status:
        stmt = stmt.where(Content.status == status)
    if project_id:
        stmt = stmt.where(Content.project_id == project_id)
    if mine:
        stmt = stmt.where(Content.owner_id == user.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Content.name.like(like), Content.key.like(like)))
    stmt = stmt.order_by(Content.updated_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=ContentOut, summary="创建内容（可从模板实例化）")
def create_content(req: ContentCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> Content:
    schema = req.schema_
    template_id = req.template_id
    if schema is None and template_id:
        t = db.get(Template, template_id)
        if t is None:
            raise HTTPException(404, "模板不存在")
        schema = instantiate(t.schema, kind=req.kind, name=req.name,
                             locale=req.locale, theme_id=req.theme_id or "")
    if schema is None:
        schema = empty_schema(req.kind, name=req.name, locale=req.locale)
    key = req.key or next_key(req.kind, [c.key for c in db.execute(select(Content)).scalars()])
    try:
        return services.create_content(
            db, user=user, kind=req.kind, name=req.name, schema_=schema, key=key,
            locale=req.locale, project_id=req.project_id, template_id=template_id,
            theme_id=req.theme_id)
    except services.ServiceError as exc:
        raise _err(exc) from exc


@router.get("/stats", summary="内容统计")
def stats(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return services.usage_stats(db)


@router.get("/{content_id}", response_model=ContentOut)
def get_content(content_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Content:
    return _get_content(db, content_id)


@router.get("/{content_id}/schema", summary="取当前版本的 Block Schema")
def get_schema(content_id: str, version: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    c = _get_content(db, content_id)
    v = services.get_version(db, c, version)
    return {"content_id": c.id, "version": v.version, "version_id": v.id,
            "schema": v.schema, "lint": v.lint_result}


@router.get("/{content_id}/preview", summary="实时预览（HTML + lint + 结构摘要）")
def preview(content_id: str, version: int | None = None,
            tokens: str | None = Query(None, description="JSON 形式的 token 覆盖"),
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict:
    c = _get_content(db, content_id)
    v = services.get_version(db, c, version)
    override = None
    if tokens:
        import json
        try:
            override = json.loads(tokens)
        except Exception:
            override = None
    toks = resolve_tokens(v.schema, override or {})
    pv = render_preview(v.schema, kind=c.kind, tokens=toks)
    return {"content_id": c.id, "version": v.version, **pv}


@router.patch("/{content_id}", response_model=ContentOut, summary="更新元信息")
def update_content(content_id: str, req: ContentUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> Content:
    c = _get_content(db, content_id)
    if req.lock_version is not None and req.lock_version != c.lock_version:
        raise _err(services.ServiceError("版本冲突：内容已被他人更新", 409,
                                         current=c.lock_version))
    if req.name:
        c.name = req.name
    if req.locale:
        c.locale = req.locale
    if req.theme_id is not None:
        c.theme_id = req.theme_id
    if req.meta is not None:
        c.meta = {**(c.meta or {}), **req.meta}
    if req.status and req.status != c.status:
        try:
            c, _ = services.transition(db, c, user, req.status, reason=req.reason)
        except services.ServiceError as exc:
            raise _err(exc) from exc
    db.commit()
    db.refresh(c)
    return c


@router.post("/{content_id}/save", response_model=ContentOut, summary="保存为新版本")
def save(content_id: str, req: ContentSave, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)) -> Content:
    c = _get_content(db, content_id)
    try:
        return services.save_content(
            db, content=c, user=user, schema=req.schema_, message=req.message,
            create_version=req.create_version, lint_gate=req.lint_gate,
            lock_version=req.lock_version, force=True)
    except services.ServiceError as exc:
        raise _err(exc) from exc


# ---------------------------------------------------------------- 版本

@router.get("/{content_id}/versions", response_model=list[VersionOut])
def versions(content_id: str, limit: int = Query(50, le=200),
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> list[ContentVersion]:
    c = _get_content(db, content_id)
    return list(db.execute(
        select(ContentVersion).where(ContentVersion.content_id == c.id)
        .order_by(ContentVersion.version.desc()).limit(limit)).scalars())


@router.get("/{content_id}/versions/{version}", summary="查看某版本 + 与上一版 diff")
def version_detail(content_id: str, version: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> dict:
    from ...blocks.schema import schema_diff
    c = _get_content(db, content_id)
    v = services.get_version(db, c, version)
    prev = db.execute(
        select(ContentVersion).where(ContentVersion.content_id == c.id,
                                     ContentVersion.version == version - 1)
    ).scalar_one_or_none()
    return {"version": v.version, "schema": v.schema, "meta": v.version_meta,
            "lint": v.lint_result, "author": v.author_name,
            "created_at": v.created_at.isoformat(),
            "diff": schema_diff(prev.schema if prev else None, v.schema)}


@router.post("/{content_id}/versions/{version}/restore", response_model=ContentOut,
             summary="回滚（追加新版本）")
def restore(content_id: str, version: int, message: str = "",
            db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Content:
    c = _get_content(db, content_id)
    try:
        services.rollback(db, c, user, version, message)
    except services.ServiceError as exc:
        raise _err(exc) from exc
    db.commit()
    db.refresh(c)
    return c


@router.get("/{content_id}/diff", summary="任意两版本对比")
def diff(content_id: str, from_version: int, to_version: int,
         db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from ...blocks.schema import schema_diff
    c = _get_content(db, content_id)
    a = services.get_version(db, c, from_version)
    b = services.get_version(db, c, to_version)
    return {"from": from_version, "to": to_version, **schema_diff(a.schema, b.schema)}


# ---------------------------------------------------------------- 协作

@router.post("/{content_id}/lock", summary="草稿锁（acquire/release/heartbeat）")
def lock(content_id: str, req: LockIn, db: Session = Depends(get_db),
         user: User = Depends(get_current_user)) -> dict:
    c = _get_content(db, content_id)
    try:
        if req.action == "acquire":
            return services.acquire_lock(db, c, user, req.ttl_seconds)
        if req.action == "heartbeat":
            return services.acquire_lock(db, c, user, req.ttl_seconds)
        return services.release_lock(db, c, user)
    except services.ServiceError as exc:
        raise _err(exc) from exc


@router.get("/{content_id}/comments", response_model=list[CommentOut])
def comments(content_id: str, unresolved_only: bool = False,
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> list[Comment]:
    c = _get_content(db, content_id)
    return services.list_comments(db, c.id, unresolved_only=unresolved_only)


@router.post("/{content_id}/comments", response_model=CommentOut)
def add_comment(content_id: str, req: CommentIn, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> Comment:
    c = _get_content(db, content_id)
    row = Comment(content_id=c.id, block_id=req.block_id, body=req.body,
                  author_id=user.id, author_name=user.name)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{content_id}/comments/{comment_id}/resolve", response_model=CommentOut)
def resolve_comment(content_id: str, comment_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> Comment:
    row = db.get(Comment, comment_id)
    if row is None or row.content_id != content_id:
        raise HTTPException(404, "评论不存在")
    row.resolved = True
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------- 审核

@router.get("/{content_id}/reviews", response_model=list[ReviewOut])
def reviews(content_id: str, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> list[ReviewTask]:
    c = _get_content(db, content_id)
    return list(db.execute(select(ReviewTask).where(ReviewTask.content_id == c.id)
                           .order_by(ReviewTask.created_at.desc())).scalars())


@router.post("/{content_id}/review", summary="状态流转（提交审核/通过/发布/归档）")
def review(content_id: str, req: ReviewIn, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> dict:
    c = _get_content(db, content_id)
    try:
        content, task = services.transition(db, c, user, req.to_status,
                                            reason=req.reason,
                                            assignee_id=req.assignee_id)
    except services.ServiceError as exc:
        raise _err(exc) from exc
    return {"content": {"id": content.id, "status": content.status,
                        "label": ContentStatus.LABEL[content.status]},
            "review": {"id": task.id, "state": task.state, "to_status": task.to_status}}


# ---------------------------------------------------------------- 导出

@router.post("/{content_id}/export", response_model=ExportOut, summary="导出产物")
def export(content_id: str, req: ExportRequest, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> ExportOut:
    c = _get_content(db, content_id)
    version = db.get(ContentVersion, req.version_id) if req.version_id else None
    if version is None:
        version = services.get_version(db, c, None)
    if version.content_id != c.id:
        raise HTTPException(400, "版本不属于该内容")

    pv = render_preview(version.schema, kind=c.kind, tokens=resolve_tokens(version.schema))
    lint = pv["lint"]
    if req.target in ("single_html", "bundle", "scaffold") and not req.allow_lint_error:
        if not lint["passed"]:
            errors = [i for i in lint["issues"] if i["severity"] == "error"]
            raise HTTPException(422, {"message": f"可投递性检查未通过（{len(errors)} 个 error）",
                                      "lint": lint, "errors": errors})

    job = ExportJob(content_id=c.id, version_id=version.id, target=req.target,
                    options=req.model_dump(), created_by=user.id)
    db.add(job)
    db.flush()
    out: dict[str, Any] = {}
    html: str | None = None
    mres: dict[str, Any] | None = None
    message = ""

    try:
        if req.target == "single_html":
            r = exporter.export_single_html(version.schema)
            out = {"filename": r["filename"], "css": r["css"]}
            html = r["html"]
        elif req.target == "bundle":
            r = exporter.export_bundle(version.schema)
            out = r
            c.export_path = r["zip"]
        elif req.target == "scaffold":
            r = exporter.export_scaffold(version.schema)
            out = r
            c.export_path = r["zip"]
        elif req.target == "mautic":
            if not settings.mautic_configured:
                raise HTTPException(400, "Mautic 未配置（MAUTIC_API_ENABLED / BASE_URL / 账号）")
            client = mautic_mod.MauticClient()
            res = mautic_mod.push_content(
                client, version.schema, name=c.name, publish=req.publish,
                update_id=c.mautic_asset_id if (req.update_mautic and c.mautic_asset_id) else None,
                redirect_url=req.redirect_url)
            if not res.ok:
                job.status = "failed"
                job.error = res.error
                db.commit()
                raise HTTPException(502, f"Mautic 投递失败: {res.error}")
            c.mautic_asset_id = res.asset_id
            mres = {"ok": True, "action": res.action, "asset_id": res.asset_id,
                    "asset_type": res.asset_type, "path": res.url,
                    "warnings": res.warnings or []}
            message = f"已推送到 Mautic（{res.asset_type} #{res.asset_id}）"
            out = {"mautic": mres}
    except HTTPException:
        job.status = "failed"
        db.commit()
        raise
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)[:2000]
        db.commit()
        raise HTTPException(500, f"导出失败: {exc}") from exc

    job.status = "success"
    job.result = {**out, "lint": lint, "message": message}
    if req.target == "single_html":
        job.result["html_bytes"] = len(html or "")
    db.commit()

    return ExportOut(job_id=job.id, target=req.target, status=job.status, files=out,
                     html=html, lint=lint, mautic=mres, message=message)


@router.get("/export/jobs/{job_id}", summary="查导出任务")
def export_job(job_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict:
    j = db.get(ExportJob, job_id)
    if j is None:
        raise HTTPException(404, "任务不存在")
    return {"id": j.id, "target": j.target, "status": j.status, "result": j.result,
            "error": j.error, "created_at": j.created_at.isoformat()}


@router.get("/{content_id}/download", summary="下载当前版本的单文件 HTML")
def download(content_id: str, version: int | None = None, inline: bool = True,
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)) -> Any:
    from fastapi.responses import HTMLResponse
    from urllib.parse import quote
    c = _get_content(db, content_id)
    v = services.get_version(db, c, version)
    r = exporter.export_single_html(v.schema)
    filename = r["filename"]
    # Content-Disposition 只允许 latin-1：中文名必须走 RFC 5987 的 filename*，
    # 同时给一个 ASCII 兜底名，避免老浏览器拿到乱码。
    ascii_name = "".join(ch if ord(ch) < 128 else "_" for ch in filename) or "content.html"
    disp = "inline" if inline else "attachment"
    headers = {
        "Content-Disposition": (
            f"{disp}; filename=\"{ascii_name}\"; "
            f"filename*=UTF-8''{quote(filename)}"
        )
    }
    return HTMLResponse(r["html"], headers=headers)


@router.post("/{content_id}/duplicate", response_model=ContentOut, summary="复制一份")
def duplicate(content_id: str, name: str = "", db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> Content:
    c = _get_content(db, content_id)
    schema = services.current_schema(db, c)
    key = next_key(c.kind, [x.key for x in db.execute(select(Content)).scalars()])
    new_name = name or f"{c.name} 副本"
    return services.create_content(
        db, user=user, kind=c.kind, name=new_name, schema_=schema, key=key,
        locale=c.locale, project_id=c.project_id, theme_id=c.theme_id,
        meta={**(c.meta or {}), "duplicated_from": c.id})


@router.get("/{content_id}/structure", summary="大纲结构（前端 Outline 树）")
def structure(content_id: str, version: int | None = None, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> dict:
    c = _get_content(db, content_id)
    v = services.get_version(db, c, version)
    return extract_info(v.schema)


# ---------------------------------------------------------------- templates/themes（前缀独立）

tpl_router = APIRouter(prefix="/templates", tags=["templates"])
theme_router = APIRouter(prefix="/themes", tags=["themes"])


@tpl_router.get("", response_model=list[TemplateOut])
def list_templates(kind: str | None = None, scenario: str | None = None,
                   q: str | None = None, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> list[Template]:
    stmt = select(Template).where(Template.is_active.is_(True))
    if kind:
        stmt = stmt.where(Template.kind == kind)
    if scenario:
        stmt = stmt.where(Template.scenario == scenario)
    if q:
        stmt = stmt.where(Template.name.like(f"%{q}%"))
    return list(db.execute(stmt.order_by(Template.kind, Template.scenario)).scalars())


@tpl_router.get("/scenarios")
def scenarios(db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...intent.lexicon import SCENARIO
    return {"scenarios": sorted(SCENARIO.keys()),
            "from_plugins": [t.key for t in db.execute(
                select(Template).where(Template.source_plugin.is_not(None))).scalars()]}


@tpl_router.get("/{template_id}/preview", summary="模板预览 HTML")
def tpl_preview(template_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict:
    from ...export.templates import template_preview_html
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    theme = db.get(Theme, t.theme_id) if t.theme_id else None
    return {"id": t.id, "name": t.name, "kind": t.kind,
            "html": template_preview_html(t.schema, theme.tokens if theme else None)}


@tpl_router.post("/{template_id}/instantiate", response_model=ContentOut,
                 summary="由模板实例化新内容")
def tpl_instantiate(template_id: str, name: str, kind: str | None = None,
                    locale: str = "zh-CN", db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> Content:
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(404, "模板不存在")
    key = next_key(kind or t.kind, [x.key for x in db.execute(select(Content)).scalars()])
    schema = instantiate(t.schema, kind=kind or t.kind, name=name, key=key, locale=locale)
    schema["doc"]["key"] = key
    c = services.create_content(db, user=user, kind=kind or t.kind, name=name,
                                schema_=schema, key=key, locale=locale, template_id=t.id)
    services.bump_template_usage(db, t.id)
    db.commit()
    db.refresh(c)
    return c


@theme_router.get("", response_model=list[ThemeOut])
def list_themes(kind: str | None = None, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)) -> list[Theme]:
    stmt = select(Theme)
    if kind:
        stmt = stmt.where(Theme.kind_scope.in_([kind, "all"]))
    return list(db.execute(stmt.order_by(Theme.is_builtin.desc(), Theme.name)).scalars())


@theme_router.get("/tokens", summary="全部 token 定义（含 label/type/default）")
def tokens(kind: str | None = None, theme_id: str | None = None,
           db: Session = Depends(get_db),
           user: User = Depends(get_current_user)) -> dict:
    from ...render.theme import tokens_to_map, tokens_to_css, merge_tokens, default_tokens
    if theme_id:
        t = db.get(Theme, theme_id)
        base = merge_tokens(default_tokens(), t.tokens if t else None)
    else:
        base = default_tokens()
    return {"tokens": tokens_to_map(base), "css": tokens_to_css(base)}