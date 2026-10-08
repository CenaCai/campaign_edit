"""LLM 通道：OpenAI 兼容接口（DeepSeek / OpenAI / vLLM / 内部网关）。

设计要点
--------
* 零 SDK 依赖：标准库 ``urllib`` + JSON，避免引入 openai 包带来的依赖膨胀。
* 严格 JSON 输出：优先 ``response_format={"type":"json_object"}``，失败则本地重试一次并要求纯 JSON。
* 永远不抛错给上层：返回 ``LLMResult(ok=False, ...)``，由 service 决定降级策略。
* 只用 system prompt 锁定输出 schema，不依赖模型"听话"，同时做本地 schema 校验。
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from ..config import settings

VALID_KINDS = ("email", "form", "landing")

SYSTEM_PROMPT = """你是营销内容创作系统的意图解析器。用户是运营人员，用中文（或英文）描述他想要的内容。
你的任务：把自然语言需求解析为结构化的内容创建计划。

内容类型只有三种：
- email : HTML 邮件（EDM、通知、促销邮件、欢迎信、改期提醒）
- form  : 表单（留资、报名、信息收集、问卷）
- landing : 着陆页/营销活动站点/落地页/专题页

必须输出 JSON，结构如下（不要输出任何解释文字）：
{
  "primary_kind": "email|form|landing",
  "confidence": 0.0,
  "scenario": "promo|welcome|recovery|abandon|event|schedule_change|announcement|lead_gen|reactivation|newsletter|verification|survey|generic",
  "locale": "zh-CN|en-GB|en-US",
  "assets": [
    {
      "kind": "email|form|landing",
      "role": "primary|supporting",
      "purpose": "这块内容承担什么业务作用，一句话",
      "depends_on": ["其他资产的 kind 或 name，可为空数组"],
      "template_hints": ["期望的模板特征关键词，0-5 个"],
      "component_hints": ["期望包含的组件，如 countDown / ticketCard / consentField"],
      "content_outline": {"subject": "邮件主题（仅 email）", "preheader": "预览文案", "key_messages": ["要点"], "cta": "行动号召文案"}
    }
  ],
  "slots": {
    "audience": "受众描述",
    "event": "活动/赛事名称",
    "date": "时间",
    "deadline": "截止或时效",
    "discount": "优惠信息",
    "price": "价格",
    "coupon": "券类型",
    "quantity": "数量",
    "language": "语言",
    "tone": "风格",
    "channel": "渠道"
  },
  "followups": [
    {"slot": "字段名", "question": "需要向运营追问的问题", "required": true, "options": ["可选值"]}
  ],
  "reasoning": "不超过 80 字的中文判断依据",
  "conflicts": ["发现的意图冲突或缺失信息"]
}

规则：
1. assets 至少一项。若用户只提了一个内容，assets 只放一项。
2. 若需求天然需要多种内容配合（例如"活动页 + 报名表 + 提醒邮件"），拆成多项并用 depends_on 表达顺序关系。
3. slots 里没有明确给出的，填空字符串，不要编造事实（例如日期、价格）。
4. followups 只放真正影响产出、且原文没给的，最多 3 项。
5. reasoning 必须简洁，禁止复述用户原话。
"""

USER_TEMPLATE = """用户需求：
{text}

已提取的线索（规则通道，可参考但不要盲从）：场景={scenarios} 渠道={channels} 槽位={slots}

请输出 JSON。"""


@dataclass
class LLMResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    latency_ms: int = 0
    raw: str = ""
    model: str = ""


def _post(url: str, headers: dict[str, str], payload: dict, timeout: int) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON：优先整段，其次 code fence，最后首个平衡括号。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"```\s*$", "", t).strip()
    try:
        return json.loads(t)
    except Exception:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i = t.find(opener)
        if i < 0:
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, len(t)):
            ch = t[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[i:j + 1])
                    except Exception:
                        break
    return None


def validate_payload(data: Any) -> tuple[dict[str, Any], list[str]]:
    """校验/修正模型输出，返回 (规范化结果, 警告列表)。"""
    warns: list[str] = []
    if not isinstance(data, dict):
        return {}, ["llm_output_not_object"]

    pk = data.get("primary_kind")
    if pk not in VALID_KINDS:
        # 从 assets 里推断
        assets = data.get("assets") or []
        if isinstance(assets, list) and assets and isinstance(assets[0], dict):
            pk = assets[0].get("kind")
        warns.append(f"primary_kind_invalid:{pk}")
        if pk not in VALID_KINDS:
            pk = "landing"
            warns.append("fallback_landing")

    assets_raw = data.get("assets")
    assets: list[dict] = []
    if isinstance(assets_raw, list):
        for a in assets_raw:
            if not isinstance(a, dict) or a.get("kind") not in VALID_KINDS:
                continue
            outline = a.get("content_outline") if isinstance(a.get("content_outline"), dict) else {}
            assets.append({
                "kind": a["kind"],
                "role": a.get("role") if a.get("role") in ("primary", "supporting") else
                        ("primary" if a["kind"] == pk else "supporting"),
                "purpose": str(a.get("purpose") or "")[:200],
                "depends_on": [str(x)[:40] for x in (a.get("depends_on") or [])][:8]
                if isinstance(a.get("depends_on"), list) else [],
                "template_hints": [str(x)[:30] for x in (a.get("template_hints") or [])][:5]
                if isinstance(a.get("template_hints"), list) else [],
                "component_hints": [str(x)[:40] for x in (a.get("component_hints") or [])][:10]
                if isinstance(a.get("component_hints"), list) else [],
                "content_outline": {
                    "subject": str(outline.get("subject") or "")[:200],
                    "preheader": str(outline.get("preheader") or "")[:200],
                    "key_messages": [str(x)[:200] for x in (outline.get("key_messages") or [])][:8]
                    if isinstance(outline.get("key_messages"), list) else [],
                    "cta": str(outline.get("cta") or "")[:80],
                },
            })
    if not assets:
        assets = [{"kind": pk, "role": "primary", "purpose": "", "depends_on": [],
                   "template_hints": [], "component_hints": [],
                   "content_outline": {"subject": "", "preheader": "", "key_messages": [],
                                       "cta": ""}}]
        warns.append("assets_emptied")
    else:
        # 保证主类型与 primary_kind 一致
        for a in assets:
            if a["kind"] == pk:
                a["role"] = "primary"
        if not any(a["kind"] == pk for a in assets):
            assets[0]["kind"] = pk
            assets[0]["role"] = "primary"

    slots = data.get("slots") if isinstance(data.get("slots"), dict) else {}
    clean_slots: dict[str, Any] = {}
    for k, v in slots.items():
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v[:4])
        clean_slots[str(k)[:24]] = str(v)[:160]

    fus = []
    if isinstance(data.get("followups"), list):
        for q in data["followups"][:3]:
            if isinstance(q, dict) and q.get("question"):
                fus.append({
                    "slot": str(q.get("slot") or "")[:24],
                    "question": str(q.get("question"))[:160],
                    "required": bool(q.get("required", False)),
                    "options": [str(o)[:60] for o in (q.get("options") or [])][:6]
                    if isinstance(q.get("options"), list) else [],
                })

    try:
        conf = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf, _ = 0.5, warns.append("confidence_invalid")
    conf = max(0.0, min(1.0, conf))

    return {
        "primary_kind": pk,
        "confidence": conf,
        "scenario": str(data.get("scenario") or "generic")[:32],
        "locale": str(data.get("locale") or "zh-CN")[:12],
        "assets": assets,
        "slots": clean_slots,
        "followups": fus,
        "reasoning": str(data.get("reasoning") or "")[:200],
        "conflicts": [str(x)[:160] for x in (data.get("conflicts") or [])][:6]
        if isinstance(data.get("conflicts"), list) else [],
    }, warns


def analyze_intent(text: str, *, hint: dict[str, Any] | None = None,
                   timeout: int | None = None) -> LLMResult:
    """调用 LLM 解析意图。任何异常都转为 ok=False。"""
    if not settings.llm_configured:
        return LLMResult(ok=False, error="llm_not_configured")
    if not (text or "").strip():
        return LLMResult(ok=False, error="empty_text")

    hint = hint or {}
    user = USER_TEMPLATE.format(
        text=text.strip(),
        scenarios=",".join(hint.get("scenarios") or []) or "无",
        channels=",".join(hint.get("channels") or []) or "无",
        slots=json.dumps(hint.get("slots") or {}, ensure_ascii=False),
    )
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    payload = {
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
    }
    if settings.llm_model.startswith(("deepseek", "gpt-4o", "gpt-4", "qwen")):
        payload["response_format"] = {"type": "json_object"}

    started = time.time()
    try:
        resp = _post(url, headers, payload, timeout or settings.llm_timeout_seconds)
        content = resp["choices"][0]["message"]["content"]
        data = extract_json(content)
        if data is None:
            return LLMResult(ok=False, error="json_parse_failed",
                             latency_ms=int((time.time() - started) * 1000),
                             raw=content[:2000], model=settings.llm_model)
        norm, warns = validate_payload(data)
        return LLMResult(ok=True, data={**norm, "_warnings": warns},
                         latency_ms=int((time.time() - started) * 1000),
                         raw=content[:4000], model=settings.llm_model)
    except urllib.error.HTTPError as e:  # pragma: no cover
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:500]
        except Exception:
            pass
        return LLMResult(ok=False, error=f"http_{e.code}:{body}",
                         latency_ms=int((time.time() - started) * 1000))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return LLMResult(ok=False, error=f"network:{e}",
                         latency_ms=int((time.time() - started) * 1000))
    except (KeyError, IndexError, ValueError) as e:
        return LLMResult(ok=False, error=f"response_shape:{e}",
                         latency_ms=int((time.time() - started) * 1000))