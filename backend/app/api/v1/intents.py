"""意图 API：/api/v1/intents —— 识别、确认、落地创建。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...db import get_db
from ...deps import get_current_user
from ...export.templates import (apply_intent_slots, empty_schema, instantiate,
                                next_key)
from ...intent import service as intent_service
from ...models import Content, ContentKind, IntentLog, Template, User
from ...schemas import IntentRequest, IntentResponse
from . import services

router = APIRouter(prefix="/intents", tags=["intent"])


def _log_intent(db: Session, user: User, payload: dict[str, Any]) -> IntentLog:
    row = IntentLog(
        raw_text=payload["raw_text"],
        lang="zh",
        engine=payload["engine"],
        status="resolved" if not payload["needs_confirm"] else "need_confirm",
        content_type=payload.get("content_type"),
        confidence=payload.get("confidence", 0),
        slots=payload.get("slots", {}),
        plan=payload.get("plan", []),
        candidates=payload.get("candidates", []),
        explanation=payload.get("explanation", {}),
        rule_scores=payload.get("rule_scores", {}),
        llm_payload={"error": payload.get("llm_error", ""),
                     "warnings": payload.get("warnings", [])},
        latency_ms=payload.get("latency_ms", 0),
        created_by=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("", response_model=IntentResponse, summary="识别意图（默认只识别不创建）")
def recognize(req: IntentRequest, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)) -> IntentResponse:
    templates = list(db.execute(
        select(Template).where(Template.is_active.is_(True))
    ).scalars())
    payload = intent_service.recognize(req.text, templates=templates, use_llm=req.use_llm)

    if not payload.get("ok"):
        raise HTTPException(400, payload.get("error", "识别失败"))

    row = _log_intent(db, user, payload)
    created: list[dict[str, Any]] = []

    if req.auto_create:
        # 只有高置信度且规则/LLM 一致时才自动创建，否则要求人工确认
        if payload["confidence"] < settings.intent_min_confidence or payload["needs_confirm"]:
            payload["explanation"]["auto_create_blocked"] = (
                "置信度不足或存在分歧/必填追问，已跳过自动创建，请确认后重试。"
            )
        else:
            created = _create_from_plan(db, user, payload, row.id, req.project_id,
                                        req.publish)
            payload["plan"] = _decorate_plan(payload["plan"], db)

    return IntentResponse(id=row.id, created_contents=created, **payload)


def _decorate_plan(plan: list[dict], db: Session) -> list[dict]:
    """把模板 ID 展开成名称，前端直接展示。"""
    ids = [p["template_id"] for p in plan if p.get("template_id")]
    if not ids:
        return plan
    rows = db.execute(select(Template).where(Template.id.in_(ids))).scalars().all()
    name_map = {r.id: r.name for r in rows}
    for p in plan:
        if p.get("template_id"):
            p["template_name"] = name_map.get(p["template_id"], "")
    return plan


def _create_from_plan(db: Session, user: User, payload: dict[str, Any], intent_id: str,
                      project_id: str | None, publish: bool) -> list[dict[str, Any]]:
    """按 plan 落地创建内容（依赖顺序：表单 → 落地页 → 邮件）。"""
    order = {ContentKind.FORM: 0, ContentKind.LANDING: 1, ContentKind.EMAIL: 2}
    plan = sorted(payload.get("plan") or [], key=lambda p: order.get(p["kind"], 9))
    existing_keys = [c.key for c in db.execute(select(Content)).scalars()]
    out: list[dict[str, Any]] = []

    for p in plan:
        kind = p["kind"]
        template = db.get(Template, p["template_id"]) if p.get("template_id") else None
        base = template.schema if (template and template.schema) else empty_schema(kind)
        name = _name_for(p, payload, kind)
        key = next_key(kind, existing_keys, project_key=(project_id or ""))
        schema = instantiate(base, kind=kind, name=name, key=key,
                             locale=p.get("locale") or payload.get("locale") or "zh-CN")
        schema = apply_intent_slots(schema, p.get("slots") or payload.get("slots") or {},
                                    kind=kind)
        schema["doc"]["name"] = name
        schema["doc"]["key"] = key
        if kind == ContentKind.EMAIL:
            schema["doc"]["subject"] = (p.get("slots", {}).get("subject")
                                        or payload.get("slots", {}).get("subject")
                                        or name)
            schema["doc"]["preheader"] = (p.get("slots", {}).get("preheader")
                                          or payload.get("slots", {}).get("preheader") or "")
        if kind == ContentKind.LANDING and p.get("slots", {}).get("cta"):
            _set_first_cta(schema, str(p["slots"]["cta"]))

        content = services.create_content(
            db, user=user, kind=kind, name=name, schema_=schema, key=key,
            locale=p.get("locale") or "zh-CN", project_id=project_id,
            template_id=template.id if template else None, intent_id=intent_id,
            meta={"intent": {"scenario": p.get("scenario"), "purpose": p.get("purpose"),
                             "slots": p.get("slots", {}),
                             "template_score": p.get("template_score")}},
        )
        if publish:
            content, _ = services.transition(db, content, user, "published",
                                             reason="意图创建时直接发布")
        services.bump_template_usage(db, template.id if template else None)
        existing_keys.append(key)
        out.append({"id": content.id, "key": key, "kind": kind, "name": name,
                    "status": content.status,
                    "template": template.name if template else None,
                    "url": f"/contents/{content.id}"})

    if out:
        row = db.get(IntentLog, intent_id)
        if row:
            services.touch_intent(db, row, [o["id"] for o in out], accepted=True)
        db.commit()
    return out


def _name_for(p: dict, payload: dict, kind: str) -> str:
    scenario = p.get("scenario") or payload.get("scenario") or "general"
    label = {"promo": "促销", "welcome": "欢迎", "recovery": "挽回", "abandon": "弃单挽回",
             "event": "赛事", "schedule_change": "改期提醒", "announcement": "公告",
             "lead_gen": "留资", "reactivation": "召回", "newsletter": "简报",
             "verification": "验证", "survey": "调研"}.get(scenario, "内容")
    kind_label = {ContentKind.EMAIL: "邮件", ContentKind.FORM: "表单",
                  ContentKind.LANDING: "落地页"}.get(kind, kind)
    event = (p.get("slots") or {}).get("event") or payload.get("slots", {}).get("event")
    return " · ".join([x for x in [str(event) if event else "", f"{label}{kind_label}"] if x])


def _set_first_cta(schema: dict, text: str) -> None:
    """把 LLM/运营给的 CTA 文案写进页面第一个按钮。"""
    from ...blocks.schema import find_node, walk
    for node in walk(schema.get("root") or {}):
        if node.get("type") in ("landing.button", "email.button"):
            node.setdefault("props", {})["text"] = text[:60]
            return


@router.get("/history", summary="意图识别历史")
def history(limit: int = 50, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict[str, Any]:
    rows = db.execute(select(IntentLog).order_by(IntentLog.created_at.desc()).limit(limit)).scalars()
    return {"items": [{
        "id": r.id, "raw_text": r.raw_text[:160], "engine": r.engine, "status": r.status,
        "content_type": r.content_type, "confidence": r.confidence, "scenario":
        (r.plan[0].get("scenario") if r.plan else None),
        "accepted": r.accepted, "result_content_ids": r.result_content_ids,
        "latency_ms": r.latency_ms, "created_at": r.created_at.isoformat(),
    } for r in rows]}


@router.get("/lexicon", summary="查看当前生效的意图词典（调试用）")
def lexicon(db: Session = Depends(get_db),
            user: User = Depends(get_current_user)) -> dict[str, Any]:
    from ...intent import lexicon as L
    return {
        "direct": {k: [[w, s] for w, s in v] for k, v in L.DIRECT.items()},
        "scenarios": {k: v for k, v in L.SCENARIO.items()},
        "channels": L.CHANNEL,
        "weights": {"rule": settings.intent_rule_weight, "llm": settings.intent_llm_weight,
                    "min_confidence": settings.intent_min_confidence,
                    "auto_template_score": settings.intent_auto_template_score},
        "negations": L.NEGATIONS,
    }


@router.post("/preview", summary="不落库，仅预览识别效果")
def preview_only(text: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict[str, Any]:
    templates = list(db.execute(
        select(Template).where(Template.is_active.is_(True))).scalars())
    return intent_service.recognize(text, templates=templates)