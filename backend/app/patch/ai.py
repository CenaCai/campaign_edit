"""AI Patch 通道：把自然语言编辑指令翻译成 operations。

设计立场
--------
**LLM 只负责翻译，不负责决策落地。**
模型输出的每一个 operation 都会被 operations.py 逐条校验，
不合规直接报错并告诉用户怎么改。模型不能绕过任何约束。

为什么不给模型完整的 schema：
1. 模型改写整份 JSON 时极易破坏未涉及的节点（人工编辑全部丢失）
2. 无法在提交前告诉用户"将要改什么"
3. 无法保证幂等与可撤销

因此：模型看到的是「组件清单 + 允许的操作 + 目标类型 schema」，
产出的是一小串 operations。
"""
from __future__ import annotations

import json
from typing import Any

from ..config import settings
from ..intent.llm import extract_json
from .operations import OPS, outline_index

SYSTEM_PROMPT = """你是内容编辑器的指令翻译器。用户会描述想改什么，你要输出一组精确的操作指令。

你只输出 JSON，不解释、不寒暄。

格式：
{"operations": [ {"op": "...", "target": "组件id", "...": "..."} ]}

可用操作（op 的取值）：
- set_prop   : 改属性。必填 target, prop, value
- set_style  : 改样式。必填 target, style（用下划线命名如 background_color）, value
- set_doc    : 改文档信息。必填 field（key/name/locale/subject/preheader/description）, value
- set_token  : 改主题色/圆角等。必填 token, value（传空字符串表示重置为默认）
- add_block  : 加组件。必填 type, props；可选 parent_id（不填则加到根下）、style
- remove     : 删组件。必填 target
- move       : 移动组件。必填 target, parent_id；可选 index
- set_hidden : 显示或隐藏。必填 target, hidden（布尔）

铁律：
1. target 必须是下方「组件清单」里真实存在的 id，不得编造。
2. 只输出实现用户意图所必需的操作，不要顺手改其他组件。
3. value 必须符合属性类型（布尔给 true/false，数字给数字，不要字符串）。
4. 如果用户要求的信息不足以完成（比如没说改哪个组件），返回空数组并在 note 里说明。
5. 一次最多 8 个操作。

输出示例：
{"operations":[{"op":"set_prop","target":"b_abc123","prop":"text","value":"立即购票"}],"note":""}"""


def user_prompt(instruction: str, schema: dict, *, available_types: list[str] | None = None) -> str:
    outline = outline_index(schema)
    types = available_types or _types_for(schema.get("kind"))
    lines = [
        f"用户指令：{instruction}",
        "",
        f"内容类型：{schema.get('kind')}（根节点 id: {(schema.get('root') or {}).get('id')}）",
        "",
        "可用的组件类型（add_block 时只能从中选）：",
    ]
    lines += [f"- {t}" for t in types[:30]]
    lines += ["", "当前组件清单（target 只能取这些 id）："]
    if outline:
        for e in outline:
            props = f"  props={json.dumps(e['props'], ensure_ascii=False)}" if "props" in e else ""
            lines.append(f"- {e['id']}  [{e['type']}]  {e['label']}{props}")
    else:
        lines.append("（空，从 add_block 开始）")
    lines += ["", "请输出 JSON。"]
    return "\n".join(lines)


def _types_for(kind: str | None) -> list[str]:
    from ..blocks.registry import get_registry
    return [s.key for s in get_registry().list(kind)]


def translate(instruction: str, schema: dict, *, timeout: int | None = None) -> dict[str, Any]:
    """自然语言 → operations。返回 {ok, operations, note, error, raw}。"""
    if not settings.llm_configured:
        return _llm_unavailable()
    if not (instruction or "").strip():
        return {"ok": False, "error": "指令为空"}

    import urllib.error
    import urllib.request

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": settings.llm_model,
        "temperature": 0.0,          # 翻译任务要确定性
        "max_tokens": min(settings.llm_max_tokens, 1200),
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt(instruction.strip(), schema)},
        ],
    }
    if settings.llm_model.startswith(("deepseek", "gpt-4", "gpt-4o", "qwen")):
        payload["response_format"] = {"type": "json_object"}

    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {settings.llm_api_key}")

    try:
        with urllib.request.urlopen(req, timeout=timeout or settings.llm_timeout_seconds) as r:
            raw = json.loads(r.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        return {"ok": False, "error": f"LLM HTTP {e.code}: {body}"}
    except Exception as e:
        return {"ok": False, "error": f"LLM 调用失败: {e}"}

    data = extract_json(content)
    if not isinstance(data, dict):
        return {"ok": False, "error": "模型输出不是 JSON", "raw": (content or "")[:800]}
    ops = data.get("operations")
    if ops is None:
        return {"ok": False, "error": "模型输出缺少 operations 字段",
                "raw": (content or "")[:800]}
    if not isinstance(ops, list):
        return {"ok": False, "error": "operations 必须是数组"}
    if len(ops) > 8:
        return {"ok": False,
                "error": f"模型返回了 {len(ops)} 个操作，超过单次上限 8；"
                          f"请分多次下达指令",
                "operations": ops[:8], "note": "已截断到前 8 个"}

    bad = [o for o in ops if not isinstance(o, dict) or o.get("op") not in OPS]
    if bad:
        return {"ok": False,
                "error": f"模型返回了不支持的操作：{[o.get('op') for o in bad if isinstance(o, dict)]}",
                "operations": ops}
    return {"ok": True, "operations": ops, "note": str(data.get("note") or "")[:300]}


def _llm_unavailable() -> dict[str, Any]:
    """无LLM 时的降级：提示用户改用结构化接口，并给出可用的直接调用示例。"""
    return {
        "ok": False,
        "error": "LLM 未配置，自然语言改写不可用（内容编辑功能完整可用）",
        "fallback": {
            "how": "直接调用 POST /api/v1/contents/{id}/patch 提交 operations",
            "example": {"operations": [
                {"op": "set_prop", "target": "<组件id>", "prop": "text", "value": "新文案"}
            ]},
            "get_outline": "GET /api/v1/contents/{id}/outline 可拿到组件 id 清单",
        },
    }


def suggest_schema() -> dict[str, Any]:
    """给前端用的操作说明。"""
    return {
        "ops": [{"op": k, "desc": v} for k, v in OPS.items()],
        "limits": {"max_ops": settings.patch_max_ops, "ai_max_ops": 8},
        "ai_enabled": settings.llm_configured and settings.patch_ai_enabled,
        "note": "所有操作都会经过校验：组件必须存在、属性必须在白名单内、"
                "邮件不允许会破坏 Outlook 兼容性的样式。",
    }