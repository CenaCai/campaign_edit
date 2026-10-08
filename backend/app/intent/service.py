"""意图引擎编排层：规则 + LLM 双通道融合 → 结构化创建计划。

融合策略（heuristic arbitration，不是学术最优，但可解释、可调参、可回归）
---------------------------------------------------------------
1. 规则通道给 ``rule_scores``（证据驱动，永远可解释）。
2. LLM 通道给 ``llm_payload``（语义理解强，处理长句/多意图/隐含）。
3. 仲裁：
   * 两通道一致 → 置信度 = 加权融合（rule_w * rule_conf + llm_w * llm_conf）
   * 不一致 → 取加权分更高者，并降低置信度（乘 0.75），把分歧写进 explanation
   * LLM 不可用 → 纯规则降级，标记 ``engine=rule``、``degraded=True``
4. 模板打分：场景匹配 0.4 + 标签重叠 0.25 + 组件命中 0.15 + 语言 0.1 + 渠道 0.1
5. 追问生成：融合槽位 → 缺关键槽才问；``required=True`` 且缺失则必须人工确认。

下游（create_from_intent）拿到的 plan 已包含模板与组件建议，可直接实例化。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import settings
from ..models import ContentKind, Template
from . import lexicon, llm

# 各类型的关键槽位：缺失则影响产出质量
REQUIRED_SLOTS: dict[str, list[str]] = {
    "email": ["audience", "message_goal"],
    "form": ["audience", "field_set"],
    "landing": ["audience", "cta"],
}

SLOT_QUESTION: dict[str, str] = {
    "audience": "这批内容的核心受众是谁？",
    "message_goal": "这封邮件最主要想达成什么（拉新/复购/告知/召回）？",
    "cta": "落地页的主要行动号召是什么（例如「立即购票」「免费报名」）？",
    "field_set": "需要收集哪些字段（例如 姓名/邮箱/手机号/票种偏好）？",
    "subject": "邮件主题希望怎么写？",
    "deadline": "活动的截止时间是什么时候？",
    "event": "对应的赛事/活动名称是什么？",
    "language": "文案语言用中文、英文还是双语？",
    "discount": "优惠力度是多少（例如 8 折 / 立减 £20）？",
    "tone": "希望什么视觉与文案风格？",
}


@dataclass
class ChannelResult:
    kind: str | None = None
    confidence: float = 0.0
    scores: dict[str, float] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)
    error: str = ""
    latency_ms: int = 0
    #: 该通道是否成功产出结论。规则通道恒为 True；LLM 通道由 error 决定。
    ok: bool = True

    def __post_init__(self) -> None:
        # 有 error 即视为失败，避免调用方漏判
        if self.error:
            self.ok = False


def _rule_channel(text: str) -> tuple[ChannelResult, dict]:
    raw = lexicon.score(text)
    top = max(raw["scores"], key=lambda k: raw["scores"][k])
    slots = lexicon.extract_slots(text)
    if raw["scores"][top] <= 0:
        return ChannelResult(kind=None, confidence=0.0, scores=raw["scores"], error="no_rule_hit"), raw
    return ChannelResult(
        kind=top,
        confidence=float(raw["confidence"]),
        scores=raw["scores"],
        payload={
            "scenarios": raw["scenarios"],
            "channels": raw["channels"],
            "tones": raw["tones"],
            "slots": slots,
            "segments": lexicon.detect_multi_intent(text),
        },
        evidence=raw["evidence"],
    ), raw


def _llm_channel(text: str, hint: dict) -> ChannelResult:
    res = llm.analyze_intent(text, hint=hint)
    if not res.ok:
        return ChannelResult(error=res.error)
    d = res.data
    return ChannelResult(
        kind=d["primary_kind"],
        confidence=float(d["confidence"]),
        scores={k: (0.0 if k != d["primary_kind"] else d["confidence"]) for k in ContentKind.ALL},
        payload=d,
        latency_ms=res.latency_ms,
        evidence=[{"layer": "llm", "keyword": d.get("reasoning", "")[:80],
                   "kind": d["primary_kind"], "weight": round(d["confidence"], 2)}],
    )


def _merge_slots(rule_slots: dict, llm_slots: dict) -> dict[str, Any]:
    """规则槽位是硬抽取（正则，不会编造），优先；LLM 补充语义槽。"""
    merged: dict[str, Any] = {}
    for k, v in (llm_slots or {}).items():
        merged[k] = v
    for k, v in (rule_slots or {}).items():
        merged[k] = v  # 规则覆盖 LLM，避免编造日期/价格
    return {k: v for k, v in merged.items() if v not in ("", None, [], {})}


def _build_plan(kind: str, scenario: str, slots: dict, role: str,
                purpose: str = "", depends_on: list | None = None) -> dict[str, Any]:
    return {
        "kind": kind,
        "role": role,
        "purpose": purpose or f"{ContentKind.LABEL.get(kind, kind)}（场景：{scenario}）",
        "scenario": scenario,
        "locale": slots.get("language") if str(slots.get("language", "")).startswith("EN") else "zh-CN",
        "slots": slots,
        "depends_on": depends_on or [],
        "template_id": None,
        "template_score": 0.0,
        "template_candidates": [],
        "component_hints": [],
    }


def _score_template(tpl: Template, kind: str, scenario: str, slots: dict,
                    text: str, component_hints: list[str]) -> float:
    """模板匹配打分。全部归一到 [0,1]。"""
    score = 0.0
    detail: dict[str, float] = {}

    # 1) 场景
    if tpl.scenario and tpl.scenario != "generic":
        if tpl.scenario == scenario:
            score += 0.40
            detail["scenario"] = 0.40
        elif scenario in (tpl.tags or []):
            score += 0.15
            detail["scenario_partial"] = 0.15

    # 2) 标签重叠（规则证据关键词 vs 模板标签）
    tags = set(tpl.tags or [])
    if tags:
        evidence_words = {e["keyword"] for e in []}  # 占位，实际用文本匹配
        flat = (text or "").lower()
        hits = 0
        for t in tags:
            tl = str(t).lower()
            if tl and (tl in flat):
                hits += 1
        if hits:
            ratio = min(1.0, hits / 3.0)
            add = 0.25 * ratio
            score += add
            detail["tags"] = round(add, 3)
        del evidence_words

    # 3) 组件命中（LLM 的 component_hints vs 模板 tags/description）
    if component_hints:
        blob = f"{tpl.name} {tpl.description} {' '.join(str(t) for t in (tpl.tags or []))}".lower()
        hits = sum(1 for h in component_hints if str(h).lower() in blob)
        if hits:
            add = 0.15 * min(1.0, hits / 2.0)
            score += add
            detail["components"] = round(add, 3)

    # 4) 语言
    lang = str(slots.get("language") or "")
    if tpl.locale and lang:
        if lang.lower().startswith(tpl.locale.lower().split("-")[0]):
            score += 0.10
            detail["locale"] = 0.10

    # 5) 渠道
    ch_slot = str(slots.get("channel") or "").lower()
    if ch_slot and tpl.channel and ch_slot in str(tpl.channel).lower():
        score += 0.10
        detail["channel"] = 0.10

    # 6) 轻度加权：用过多次说明团队偏好
    if tpl.usage_count:
        score += min(0.05, 0.01 * (1 + _log10(tpl.usage_count)))

    tpl_meta = getattr(tpl, "_score_detail", None)
    if tpl_meta is not None:
        tpl_meta.clear()
        tpl_meta.update(detail)
    return round(min(1.0, score), 4)


def _log10(n: int) -> float:
    import math
    return math.log10(max(1, n))


def _followups(kind: str, slots: dict, llm_followups: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen = set()
    for q in llm_followups or []:
        slot = q.get("slot")
        if slot in seen:
            continue
        # LLM 问的槽若规则已抽出（多为事实类），直接丢弃
        if slot in ("date", "price", "discount", "quantity", "event") and slots.get(slot):
            continue
        seen.add(slot)
        out.append(q)
    for slot in REQUIRED_SLOTS.get(kind, []):
        if slot in seen or slots.get(slot):
            continue
        seen.add(slot)
        out.append({"slot": slot, "question": SLOT_QUESTION.get(slot, f"请补充 {slot}"),
                    "required": True, "options": []})
    return out[:3]


def recognize(text: str, *, templates: list[Template] | None = None,
              use_llm: bool = True) -> dict[str, Any]:
    """主入口：自然语言 → 结构化识别结果。"""
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "empty_text"}

    rule, raw_rule = _rule_channel(text)
    hint = {"scenarios": raw_rule.get("scenarios", []),
            "channels": raw_rule.get("channels", []),
            "slots": raw_rule.get("slots", {}) or lexicon.extract_slots(text)}

    llm_res = _llm_channel(text, hint) if (use_llm and settings.llm_configured) else ChannelResult(
        error="disabled" if not settings.llm_configured else "skipped")

    explanation: dict[str, Any] = {
        "channels": {}, "agreed": False, "arbiter": "", "degraded": llm_res.error != "",
        "note": "",
    }

    # ---- 仲裁 ----
    if llm_res.ok and rule.kind:
        explanation["channels"]["rule"] = {"kind": rule.kind, "confidence": rule.confidence,
                                           "scores": rule.scores}
        explanation["channels"]["llm"] = {"kind": llm_res.kind, "confidence": llm_res.confidence}
        if llm_res.kind == rule.kind:
            kind = llm_res.kind
            conf = settings.intent_rule_weight * rule.confidence + \
                   settings.intent_llm_weight * llm_res.confidence
            explanation["agreed"] = True
            explanation["arbiter"] = "both_agree"
        else:
            rw = settings.intent_rule_weight * rule.confidence
            lw = settings.intent_llm_weight * llm_res.confidence
            kind = rule.kind if rw >= lw else llm_res.kind
            conf = max(rw, lw) * 0.75  # 分歧降置信
            explanation["arbiter"] = "rule_wins" if rw >= lw else "llm_wins"
            explanation["note"] = (
                f"规则判为 {rule.kind}({rule.confidence:.2f})，LLM 判为 "
                f"{llm_res.kind}({llm_res.confidence:.2f})，已按加权取 {kind} 并下调置信度。"
                "建议人工确认。"
            )
        engine = "hybrid"
    elif llm_res.ok:
        kind = llm_res.kind
        conf = llm_res.confidence
        engine = "llm"
        explanation["arbiter"] = "llm_only"
        explanation["note"] = "规则未命中，完全依赖 LLM 理解。"
    else:
        kind = rule.kind
        conf = rule.confidence
        engine = "rule"
        explanation["arbiter"] = "rule_only"
        explanation["note"] = (
            "LLM 不可用（%s），已降级为规则通道。建议配置 LLM_API_KEY 以获得完整语义理解。"
            % llm_res.error if llm_res.error else "已按配置跳过 LLM 通道。"
        )

    # ---- 组装资产计划 ----
    assets_raw = llm_res.payload.get("assets") if llm_res.ok else None
    rule_segments = rule.payload.get("segments") or []
    plan: list[dict[str, Any]] = []

    llm_slots = llm_res.payload.get("slots", {}) if llm_res.ok else {}
    slots = _merge_slots(hint["slots"], llm_slots)

    # 场景仲裁：规则命中多个场景时按优先级取最具体者；
    # LLM 判出的场景若规则也命中且更具体，则采纳 LLM（语义优先）。
    rule_scenario = lexicon.classify_scenario(text)
    llm_scenario = llm_res.payload.get("scenario") if llm_res.ok else None
    if llm_scenario and llm_scenario != "generic" and \
            llm_scenario in hint["scenarios"]:
        scenario = llm_scenario
    elif llm_scenario and llm_scenario != "generic" and not hint["scenarios"]:
        scenario = llm_scenario
    elif rule_scenario != "generic":
        scenario = rule_scenario
    elif hint["scenarios"]:
        scenario = hint["scenarios"][0]
    else:
        scenario = "generic"

    if assets_raw:
        for i, a in enumerate(assets_raw):
            a_slots = _merge_slots(slots, {})
            if a.get("content_outline"):
                a_slots = dict(a_slots)
                for f in ("subject", "preheader", "cta"):
                    if a["content_outline"].get(f):
                        a_slots[f] = a["content_outline"][f]
                if a["content_outline"].get("key_messages"):
                    a_slots["key_messages"] = a["content_outline"]["key_messages"]
            p = _build_plan(a["kind"], scenario, a_slots, a.get("role") or
                            ("primary" if i == 0 else "supporting"),
                            purpose=a.get("purpose", ""), depends_on=a.get("depends_on"))
            p["template_hints"] = a.get("template_hints") or []
            p["component_hints"] = a.get("component_hints") or []
            p["reasoning"] = llm_res.payload.get("reasoning", "")
            plan.append(p)
    elif rule_segments:
        # 规则检测到多意图分段
        for seg in rule_segments:
            p = _build_plan(seg["kind"], scenario, slots,
                            "primary" if seg is rule_segments[0] else "supporting",
                            purpose=f"片段：{seg['segment']}")
            p["source_segment"] = seg["segment"]
            plan.append(p)
    else:
        plan.append(_build_plan(kind or "landing", scenario, slots, "primary",
                                purpose=llm_res.payload.get("reasoning", "") if llm_res.ok else ""))

    # ---- 模板匹配 ----
    if templates:
        for p in plan:
            pool = [t for t in templates if t.kind == p["kind"] and t.is_active]
            scored = []
            for t in pool:
                s = _score_template(t, p["kind"], scenario, p["slots"], text, p["component_hints"])
                scored.append({"template_id": t.id, "template_key": t.key, "name": t.name,
                               "score": s, "scenario": t.scenario,
                               "thumbnail": t.thumbnail, "locale": t.locale,
                               "description": t.description})
            scored.sort(key=lambda x: -x["score"])
            p["template_candidates"] = scored[:5]
            if scored and scored[0]["score"] >= settings.intent_auto_template_score:
                p["template_id"] = scored[0]["template_id"]
                p["template_score"] = scored[0]["score"]
            elif scored:
                p["template_id"] = scored[0]["template_id"]  # 仍给推荐，但需人工确认
                p["template_score"] = scored[0]["score"]

    # ---- 追问 ----
    for p in plan:
        p["followups"] = _followups(p["kind"], p["slots"],
                                   llm_res.payload.get("followups") if llm_res.ok else [])

    # ---- 冲突/风险 ----
    conflicts: list[str] = list(llm_res.payload.get("conflicts") or []) if llm_res.ok else []
    if not explanation["agreed"] and not llm_res.ok:
        conflicts.append("LLM 通道不可用，识别结果仅基于关键词规则，长句/隐含需求可能误判。")
    if kind is None:
        conflicts.append("无法判断内容类型，需人工指定。")

    needs_confirm = (
        kind is None
        or conf < settings.intent_min_confidence
        or (not explanation["agreed"] and llm_res.ok)
        or any(p.get("template_score", 0) < settings.intent_auto_template_score for p in plan)
        or any(any(q["required"] for q in p.get("followups", [])) for p in plan)
    )

    return {
        "ok": True,
        "engine": engine,
        "raw_text": text,
        "content_type": kind,
        "confidence": round(conf, 4),
        "scenario": scenario,
        "locale": (llm_res.payload.get("locale") if llm_res.ok else None) or "zh-CN",
        "slots": slots,
        "plan": plan,
        "candidates": [{"kind": k, "score": v} for k, v in
                       sorted(raw_rule["scores"].items(), key=lambda x: -x[1])],
        "rule_scores": raw_rule["scores"],
        "rule_evidence": rule.evidence,
        "explanation": {
            **explanation,
            "scenarios": hint["scenarios"],
            "channels": hint["channels"],
            "tones": raw_rule.get("tones", []),
            "reasoning": llm_res.payload.get("reasoning", "") if llm_res.ok else "",
        },
        "needs_confirm": needs_confirm,
        "conflicts": conflicts,
        "warnings": (llm_res.payload.get("_warnings") or []) if llm_res.ok else [],
        "latency_ms": llm_res.latency_ms,
        "degraded": llm_res.error != "",
        "llm_error": llm_res.error,
    }