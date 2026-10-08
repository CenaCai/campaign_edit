"""模板工厂：从 schema 骨架实例化出内容。

模板本身就是一份 Block Schema（存DB 的 ``templates.schema``），
实例化 = 复制 + 覆盖 doc/theme + 注入意图槽位（subject/主题色/文案）。
这样"模板"和"内容"共用一套渲染与导出链路，不存在两套逻辑。
"""
from __future__ import annotations

import copy
from typing import Any

from ..blocks.registry import get_registry
from ..blocks.schema import SCHEMA_VERSION, SchemaError, new_id, normalize_schema
from ..models import ContentKind
from ..render.theme import default_tokens

KEY_PREFIX = {ContentKind.EMAIL: "EM", ContentKind.FORM: "FORM", ContentKind.LANDING: "CMP"}


def empty_schema(kind: str, *, name: str = "未命名", key: str = "",
                 locale: str = "zh-CN", theme_id: str = "") -> dict[str, Any]:
    registry = get_registry()
    root_spec = registry.root_spec(kind)
    root = root_spec.make()
    root["id"] = "root"
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "doc": {"key": key, "name": name, "locale": locale, "subject": "",
                "preheader": "", "description": ""},
        "theme": {"theme_id": theme_id, "token_overrides": {}},
        "root": root,
    }


def instantiate(template_schema: dict, *, kind: str | None = None, name: str = "",
                key: str = "", locale: str = "zh-CN", theme_id: str = "",
                token_overrides: dict | None = None, content_overrides: dict | None = None
                ) -> dict[str, Any]:
    """由模板 schema 产出新内容 schema。"""
    schema = copy.deepcopy(template_schema or {})
    kind = kind or schema.get("kind")
    if not schema.get("root"):
        schema = empty_schema(kind)
    schema["kind"] = kind
    # 容错：模板来源可能是手写 JSON，doc/theme/root 未必齐全
    schema["doc"] = dict(schema.get("doc") or {})
    schema["theme"] = dict(schema.get("theme") or {})
    schema["doc"].update({
        "key": key or schema["doc"].get("key", ""),
        "name": name or schema["doc"].get("name", ""),
        "locale": locale or schema["doc"].get("locale", "zh-CN"),
    })
    schema["theme"].setdefault("theme_id", theme_id or schema["theme"].get("theme_id", ""))
    schema["theme"]["token_overrides"] = {
        **(schema["theme"].get("token_overrides") or {}),
        **(token_overrides or {}),
    }
    if content_overrides:
        schema["doc"].update(content_overrides)
    # 重新生成节点 id，避免多份内容共享同一批 id（否则评论锚点/埋点会串）
    _reid(schema.get("root") or {})
    return normalize_schema(schema, get_registry())


def _reid(node: dict, *, is_root: bool = False) -> None:
    if not is_root:
        node["id"] = new_id("b")
    for ch in node.get("children") or []:
        _reid(ch)


def next_key(kind: str, existing: list[str], *, project_key: str = "") -> str:
    """按 CSTS 命名规范生成唯一 key：EM_WATERBOMB_20261008_A3。"""
    prefix = KEY_PREFIX.get(kind, "DOC")
    used = set(existing)
    base = project_key or ""
    tail = "V1"
    n = 1
    while True:
        parts = [p for p in (prefix, base, tail) if p]
        candidate = "_".join(parts)
        if candidate not in used:
            return candidate
        n += 1
        tail = f"V{n}"


def apply_intent_slots(schema: dict, slots: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """把意图识别抽出的槽位落到内容上（保守：只填明确字段，不猜）。"""
    out = copy.deepcopy(schema)
    doc = out.setdefault("doc", {})
    if kind == ContentKind.EMAIL:
        if slots.get("subject"):
            doc["subject"] = str(slots["subject"])[:200]
        if slots.get("preheader"):
            doc["preheader"] = str(slots["preheader"])[:200]
        if not doc.get("description") and slots.get("event"):
            doc["description"] = f"{slots['event']} 相关邮件"
    elif kind == ContentKind.LANDING:
        if not doc.get("description"):
            bits = []
            for key in ("event", "audience", "deadline"):
                if slots.get(key):
                    bits.append(str(slots[key]))
            doc["description"] = " · ".join(bits)[:180]
        if str(slots.get("language") or "").upper().startswith("EN"):
            doc["locale"] = "en-GB"
    if slots.get("audience"):
        out.setdefault("meta", {})["audience"] = str(slots["audience"])[:120]
    for k in ("event", "audience", "deadline", "discount", "coupon", "price", "quantity", "tone"):
        if slots.get(k):
            out.setdefault("meta", {})[k] = str(slots[k])[:160]
    if slots.get("tone"):
        tone_map = {"简洁": {"radius": "4px"}, "高级感": {"radius": "12px", "brand_light": "#f3f0ea"},
                    "科技感": {"brand": "#2563eb"}, "活泼": {"brand": "#f97316"},
                    "极简": {"radius": "0", "shadow": "none"}}
        ov = tone_map.get(str(slots["tone"]))
        if ov:
            out["theme"]["token_overrides"].update(ov)
    return out


def template_preview_html(template_schema: dict, tokens: dict | None = None) -> str:
    from ..render import render
    try:
        return render(template_schema, tokens=tokens or default_tokens())
    except Exception as exc:  # pragma: no cover
        return f"<pre>模板渲染失败: {exc}</pre>"


def validate_schema(schema: dict) -> dict[str, Any]:
    try:
        normalized = normalize_schema(schema, get_registry())
        return {"ok": True, "schema": normalized, "warnings": normalized.get("warnings", [])}
    except SchemaError as exc:
        return {"ok": False, "error": str(exc)}