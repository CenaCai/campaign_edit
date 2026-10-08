"""启动引导：主题 + 模板 + 示例用户 + 示例项目 + 示例内容。幂等。"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..blocks.registry import load_builtins
from ..export.templates import instantiate, next_key, validate_schema
from ..models import Content, Project, Template, Theme, User
from ..render.theme import BUILTIN_THEMES, default_tokens
from .demo import DEMO_CONTENTS, DEMO_USERS, DEMO_PROJECTS

logger = logging.getLogger("campaign_edit.seed")


def run_bootstrap(db: Session) -> dict[str, int]:
    from ..deps import bootstrap_admin, ensure_demo_users
    load_builtins()
    stats = {"themes": 0, "templates": 0, "users": 0, "projects": 0, "contents": 0}

    bootstrap_admin(db)
    stats["users"] += 1
    stats["users"] += len(ensure_demo_users(db))

    for spec in BUILTIN_THEMES:
        t = db.execute(select(Theme).where(Theme.key == spec["key"])).scalar_one_or_none()
        if t is None:
            db.add(Theme(key=spec["key"], name=spec["name"],
                         kind_scope=spec["kind_scope"], tokens=spec["tokens"],
                         css_vars={f"--{k}": v for k, v in spec["tokens"].items()},
                         is_builtin=True))
            stats["themes"] += 1
        elif not t.is_builtin:
            t.is_builtin = True

    # 完整 token 集合（内置主题也补全默认值，方便前端属性面板直接展示）
    for t in db.execute(select(Theme).where(Theme.is_builtin.is_(True))).scalars():
        full = {**default_tokens(), **(t.tokens or {})}
        t.tokens = full
        t.css_vars = {f"--{k}": v for k, v in full.items()}
    db.flush()

    from .templates_seed import ALL_TEMPLATES
    for spec in ALL_TEMPLATES:
        row = db.execute(select(Template).where(Template.key == spec["key"])).scalar_one_or_none()
        ok = validate_schema(spec["schema"])
        if not ok["ok"]:
            logger.warning("模板 %s schema 不合法，已跳过: %s", spec["key"], ok.get("error"))
            continue
        theme = None
        scope = spec["kind"]
        theme = db.execute(
            select(Theme).where(Theme.key == "csts-dark-brand")).scalar_one_or_none()
        if row is None:
            db.add(Template(
                key=spec["key"], name=spec["name"], kind=spec["kind"],
                scenario=spec.get("scenario", "generic"), locale=spec.get("locale", "zh-CN"),
                channel=spec.get("channel", ""), description=spec.get("description", ""),
                tags=spec.get("tags", []), schema=spec["schema"],
                theme_id=theme.id if theme else None, is_active=True))
            stats["templates"] += 1
        else:
            row.name, row.scenario = spec["name"], spec.get("scenario", "generic")
            row.description, row.tags, row.schema = spec.get("description", ""), \
                spec.get("tags", []), spec["schema"]
            row.is_active = True
    db.flush()

    for spec in DEMO_PROJECTS:
        if db.execute(select(Project).where(Project.key == spec["key"])).scalar_one_or_none():
            continue
        db.add(Project(**spec))
        stats["projects"] += 1
    db.flush()

    # 示例内容：从模板实例化，让首次打开就有内容可看
    admin = db.execute(select(User).where(User.role == "admin")).scalars().first()
    if admin:
        existing = {c.key for c in db.execute(select(Content)).scalars()}
        keys = list(existing)
        for spec in DEMO_CONTENTS:
            if spec["key"] in existing:
                continue
            tpl = db.execute(select(Template).where(Template.key == spec["template_key"])).scalar_one_or_none()
            if tpl is None:
                continue
            schema = instantiate(tpl.schema, kind=tpl.kind, name=spec["name"],
                                 locale=spec.get("locale", "zh-CN"))
            schema["doc"].update(spec.get("doc") or {})
            schema["doc"]["key"] = spec["key"]
            from ..api.v1.services import create_content
            try:
                c = create_content(db, user=admin, kind=tpl.kind, name=spec["name"],
                                   schema_=schema, key=spec["key"],
                                   locale=spec.get("locale", "zh-CN"),
                                   project_id=spec.get("project_id"),
                                   template_id=tpl.id,
                                   meta={"seed": True, "note": spec.get("note", "")})
                if spec.get("status") and spec["status"] != "draft":
                    c.status = spec["status"]
                db.commit()
                stats["contents"] += 1
            except Exception as exc:
                logger.warning("示例内容 %s 创建失败: %s", spec["key"], exc)
                db.rollback()
        _ = keys

    db.commit()
    logger.info("引导完成: %s", stats)
    return stats


def seed_all(db: Session, *, force: bool = False) -> dict[str, int]:
    """CLI 入口：``python -m app.seed``。force=True 会重置内置模板/主题。"""
    from ..db import SessionLocal
    load_builtins()
    with SessionLocal() as db:
        if force:
            db.query(Template).filter(Template.source_plugin.is_(None)).delete()
            db.query(Theme).filter(Theme.is_builtin.is_(True)).delete()
            db.commit()
        return run_bootstrap(db)


if __name__ == "__main__":  # pragma: no cover
    import json
    print(json.dumps(seed_all(None, force=False), ensure_ascii=False, indent=2))