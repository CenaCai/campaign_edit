"""内容服务层：版本管理、乐观锁、审核流、草稿锁。

规则（与 CSTS 线上事故经验一致）：
* 版本**只追加**，回滚也是追加新版本 —— 审计链完整；
* ``lock_version`` 做 CAS，防止两个人互相覆盖；
* 草稿锁是"软独占"，带 TTL，编辑中每30s 心跳续期；锁过期自动可抢；
* 状态机严格校验，``draft → published`` 必须经过 ``in_review``（可配置跳过，但需admin）；
* **不做 DELETE**：下线用 ``is_published=0`` / status=archived。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...blocks.registry import get_registry
from ...blocks.schema import SchemaError, normalize_schema, schema_diff
from ...models import (Comment, Content, ContentStatus, ContentVersion, IntentLog,
                      ReviewTask, Template, Theme, User)
from ...render import preview, render, resolve_tokens


class ServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite 取回的 datetime 无 tzinfo，统一补成 UTC 以便比较。"""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- 创建

def create_content(db: Session, *, user: User, kind: str, name: str, schema_: dict,
                   key: str | None = None, locale: str = "zh-CN",
                   project_id: str | None = None, template_id: str | None = None,
                   theme_id: str | None = None, intent_id: str | None = None,
                   meta: dict | None = None) -> Content:
    registry = get_registry()
    schema_ = dict(schema_)
    schema_["kind"] = kind
    schema_["doc"]["locale"] = locale
    if theme_id:
        schema_.setdefault("theme", {})["theme_id"] = theme_id
    try:
        normalized = normalize_schema(schema_, registry)
    except SchemaError as exc:
        raise ServiceError(f"schema 不合法: {exc}", 422) from exc

    if not key:
        existing = [c.key for c in db.execute(select(Content)).scalars()]
        from ..export.templates import next_key
        key = next_key(kind, existing)
    if db.execute(select(Content).where(Content.key == key)).scalar_one_or_none():
        raise ServiceError(f"key 已存在: {key}", 409)

    theme = db.get(Theme, theme_id) if theme_id else None
    if theme and theme.tokens:
        base = dict(normalized["theme"].get("token_overrides") or {})
        base.update(theme.tokens)
        normalized["theme"]["token_overrides"] = base

    c = Content(key=key, name=name, kind=kind, status=ContentStatus.DRAFT, locale=locale,
                project_id=project_id, template_id=template_id, theme_id=theme_id,
                intent_id=intent_id, owner_id=user.id, meta=meta or {},
                lock_version=0)
    db.add(c)
    db.flush()

    v = _append_version(db, content=c, schema=normalized, author=user,
                        message="初始版本")
    c.current_version = v.version
    c.current_version_id = v.id
    db.commit()
    db.refresh(c)
    return c


def _append_version(db: Session, *, content: Content, schema: dict, author: User,
                    message: str = "", lint_result: dict | None = None,
                    rendered_html: str | None = None,
                    extra_meta: dict | None = None) -> ContentVersion:
    prev = db.execute(
        select(ContentVersion).where(ContentVersion.content_id == content.id)
        .order_by(ContentVersion.version.desc()).limit(1)
    ).scalar_one_or_none()
    version = (prev.version + 1) if prev else 1
    diff = schema_diff(prev.schema if prev else None, schema)
    vm: dict[str, Any] = {"message": message[:200]}
    if extra_meta:
        vm.update(extra_meta)
    v = ContentVersion(content_id=content.id, version=version, schema=schema,
                       version_meta=vm, diff=diff, author_id=author.id,
                       author_name=author.name, lint_result=lint_result,
                       rendered_html=(rendered_html or "")[:400000] or None)
    db.add(v)
    db.flush()
    content.current_version = version
    content.current_version_id = v.id
    content.lock_version = (content.lock_version or 0) + 1
    return v


# ---------------------------------------------------------------- 保存

def save_content(db: Session, *, content: Content, user: User, schema: dict,
                 message: str = "", create_version: bool = True,
                 lint_gate: bool = True, lock_version: int | None = None,
                 force: bool = False) -> Content:
    _assert_not_locked_by_other(content, user, force=force)
    if lock_version is not None and lock_version != content.lock_version:
        raise ServiceError(
            "版本冲突：内容已被他人更新", 409,
            current_lock_version=content.lock_version, your_lock_version=lock_version,
        )
    schema = dict(schema)
    schema["kind"] = content.kind
    try:
        normalized = normalize_schema(schema, get_registry())
    except SchemaError as exc:
        raise ServiceError(f"schema 不合法: {exc}", 422) from exc

    pv = preview(normalized)
    if lint_gate and not pv["lint"]["passed"]:
        errors = [i for i in pv["lint"]["issues"] if i["severity"] == "error"]
        raise ServiceError(
            f"可投递性检查未通过（{len(errors)} 个 error）", 422,
            lint=pv["lint"], errors=errors,
        )

    if create_version:
        _append_version(db, content=content, schema=normalized, author=user,
                        message=message or "保存", lint_result=pv["lint"],
                        rendered_html=pv["html"])
    else:
        content.lock_version = (content.lock_version or 0) + 1
    content.updated_at = _now()
    db.commit()
    db.refresh(content)
    return content


def current_schema(db: Session, content: Content) -> dict:
    """取当前生效版本的 schema。"""
    if content.current_version_id:
        v = db.get(ContentVersion, content.current_version_id)
        if v:
            return v.schema
    from ..export.templates import empty_schema
    return empty_schema(content.kind, name=content.name, key=content.key)


def get_version(db: Session, content: Content, version: int | None = None) -> ContentVersion:
    if version is None:
        if content.current_version_id:
            v = db.get(ContentVersion, content.current_version_id)
            if v:
                return v
        v = db.execute(
            select(ContentVersion).where(ContentVersion.content_id == content.id)
            .order_by(ContentVersion.version.desc()).limit(1)
        ).scalar_one_or_none()
        if v:
            return v
        raise ServiceError("内容没有任何版本", 404)
    v = db.execute(select(ContentVersion).where(
        ContentVersion.content_id == content.id, ContentVersion.version == version)
    ).scalar_one_or_none()
    if v is None:
        raise ServiceError(f"版本不存在: v{version}", 404)
    return v


# ---------------------------------------------------------------- 草稿锁

def acquire_lock(db: Session, content: Content, user: User, ttl: int = 300) -> dict:
    now = _now()
    exp = _aware(content.lock_expires_at)
    if content.lock_owner_id and content.lock_owner_id != user.id and exp and exp > now:
        raise ServiceError(
            f"内容正被他人编辑（{content.lock_owner_id}）", 409,
            lock_owner=content.lock_owner_id, expires_at=exp.isoformat(),
        )
    content.lock_owner_id = user.id
    content.lock_expires_at = now + timedelta(seconds=ttl)
    db.commit()
    return {"locked_by": user.id, "expires_at": content.lock_expires_at.isoformat()}


def release_lock(db: Session, content: Content, user: User) -> dict:
    if content.lock_owner_id == user.id:
        content.lock_owner_id = None
        content.lock_expires_at = None
        db.commit()
    return {"released": True, "locked_by": content.lock_owner_id}


def _assert_not_locked_by_other(content: Content, user: User, *, force: bool = False) -> None:
    if force or not content.lock_owner_id or content.lock_owner_id == user.id:
        return
    exp = _aware(content.lock_expires_at)
    if exp and exp > _now():
        raise ServiceError(
            f"内容正被他人编辑（{content.lock_owner_id}），请先获取草稿锁或等待锁过期",
            409, lock_owner=content.lock_owner_id,
            expires_at=exp.isoformat(),
        )


# ---------------------------------------------------------------- 审核流

def transition(db: Session, content: Content, user: User, to_status: str,
               *, reason: str = "", assignee_id: str | None = None,
               skip_review: bool = False) -> tuple[Content, ReviewTask]:
    if to_status not in ContentStatus.ALL:
        raise ServiceError(f"未知状态: {to_status}")
    if to_status == content.status:
        return content, _dummy_task(content, to_status, reason)
    if not skip_review and not ContentStatus.can_transition(content.status, to_status):
        raise ServiceError(
            f"非法状态迁移：{ContentStatus.LABEL[content.status]} → "
            f"{ContentStatus.LABEL[to_status]}",
            409,
            allowed=[ContentStatus.LABEL[s] for s in
                     ContentStatus.TRANSITIONS.get(content.status, ())],
        )
    if to_status == ContentStatus.PUBLISHED and user.role not in ("admin", "editor"):
        raise ServiceError("只有 admin/editor 可以发布", 403)

    task = ReviewTask(content_id=content.id, version_id=content.current_version_id,
                      from_status=content.status, to_status=to_status, reason=reason[:2000],
                      state="pending" if to_status == ContentStatus.IN_REVIEW else "approved",
                      assignee_id=assignee_id, decided_by=None if to_status ==
                      ContentStatus.IN_REVIEW else user.id,
                      decided_at=None if to_status == ContentStatus.IN_REVIEW else _now(),
                      created_by=user.id)
    db.add(task)

    content.status = to_status
    if to_status == ContentStatus.PUBLISHED:
        content.published_version_id = content.current_version_id
    if to_status == ContentStatus.ARCHIVED:
        content.lock_owner_id = None
        content.lock_expires_at = None
    db.commit()
    db.refresh(content)
    return content, task


def _dummy_task(content: Content, to_status: str, reason: str) -> ReviewTask:
    return ReviewTask(id="", content_id=content.id, version_id=content.current_version_id,
                      from_status=content.status, to_status=to_status, reason=reason,
                      state="noop", created_at=_now())


# ---------------------------------------------------------------- 回滚

def rollback(db: Session, content: Content, user: User, target_version: int,
             message: str = "") -> ContentVersion:
    target = get_version(db, content, target_version)
    return _append_version(db, content=content, schema=target.schema, author=user,
                           message=message or f"回滚到 v{target_version}",
                           extra_meta={"rollback_from": target_version})


# ---------------------------------------------------------------- 统计

def usage_stats(db: Session) -> dict[str, Any]:
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for kind, n in db.execute(select(Content.kind, func.count(Content.id)).group_by(Content.kind)):
        by_kind[kind] = n
    for st, n in db.execute(select(Content.status, func.count(Content.id)).group_by(Content.status)):
        by_status[st] = n
    intents = db.execute(select(func.count(IntentLog.id))).scalar_one()
    plugins = db.execute(select(func.count(Template.id)).where(Template.source_plugin.is_not(None))).scalar_one()
    return {"contents_by_kind": by_kind, "contents_by_status": by_status,
            "intents": intents, "plugin_templates": plugins}


def content_preview_payload(content: Content, schema: dict, *, tokens: dict | None = None) -> dict:
    pv = preview(schema, kind=content.kind, tokens=tokens or resolve_tokens(schema))
    return pv


def list_comments(db: Session, content_id: str, *, unresolved_only: bool = False) -> list[Comment]:
    q = select(Comment).where(Comment.content_id == content_id)
    if unresolved_only:
        q = q.where(Comment.resolved.is_(False))
    return list(db.execute(q.order_by(Comment.created_at)).scalars())


def bump_template_usage(db: Session, template_id: str | None) -> None:
    if not template_id:
        return
    t = db.get(Template, template_id)
    if t:
        t.usage_count = (t.usage_count or 0) + 1
        db.flush()


def touch_intent(db: Session, intent: IntentLog, content_ids: list[str], accepted: bool = True) -> None:
    intent.accepted = accepted
    intent.result_content_ids = content_ids
    db.flush()


__all__ = [n for n in dir() if not n.startswith("_")]