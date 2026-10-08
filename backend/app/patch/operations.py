"""AI Patch —— 让 AI 操作内容，而不是重建内容。

为什么是这个
------------
从"AI 重建整个内容"到"AI 改某一处"，是产品性质的跨越：

* 重建：AI 每次输出都要重新落库，用户失去已有的人工编辑，且**不可逆**
* Patch：只改指定节点，diff 可见、可预览、可撤销，其余部分字节不变

因此本模块的硬约束是：
1. **所有操作作用于已有 schema 的局部**，不生成新 schema
2. **每个操作都要校验**（节点存在、类型允许、props 在白名单内）
3. **dry_run 先看 diff 再提交**，不盲改
4. 走既有的版本机制（追加新版本），保留审计链
5. LLM 只负责把自然语言翻译成 operations，**不直接碰 schema**
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from ..blocks.registry import get_registry
from ..blocks.schema import (ALLOWED_STYLE_KEYS, EMAIL_UNSAFE_STYLE_KEYS, find_node,
                             find_parent, new_id, normalize_schema, walk)

# 支持的操作类型
OPS = {
    "set_prop":    "修改组件的某个属性",
    "set_style":   "修改组件的样式",
    "set_doc":     "修改文档级元信息（subject / preheader / description 等）",
    "set_token":   "修改主题 token",
    "add_block":   "新增组件",
    "remove":      "删除组件",
    "move":        "移动组件到新父节点/新位置",
    "set_hidden":  "显示/隐藏组件",
}

_DOC_FIELDS = {"key", "name", "locale", "subject", "preheader", "description"}


class PatchError(ValueError):
    """操作非法。message 面向使用者，需说明怎么改。"""


@dataclass
class PatchResult:
    schema: dict
    applied: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(a.get("error") for a in self.applied)


def apply_operations(schema: dict, operations: list[dict],
                     *, dry_run: bool = False,
                     max_ops: int = 40) -> PatchResult:
    """按顺序执行 operations。任何一条失败即抛错（保证操作原子性）。"""
    if not isinstance(operations, list) or not operations:
        raise PatchError("operations 不能为空")
    if len(operations) > max_ops:
        raise PatchError(f"单次最多 {max_ops} 个操作，当前 {len(operations)}")

    work = copy.deepcopy(schema)          # 始终在副本上操作，失败不污染原 schema
    registry = get_registry()
    kind = work.get("kind")
    result = PatchResult(schema=work)

    for idx, op in enumerate(operations):
        if not isinstance(op, dict):
            raise PatchError(f"第 {idx + 1} 条操作不是对象")
        op_type = op.get("op")
        handler = _HANDLERS.get(op_type)
        if handler is None:
            raise PatchError(
                f"第 {idx + 1} 条操作类型 '{op_type}' 不支持；"
                f"可用：{', '.join(sorted(OPS))}")
        try:
            detail = handler(work, op, registry, kind)
            result.applied.append({"index": idx, "op": op_type, **detail})
        except PatchError as exc:
            raise PatchError(f"第 {idx + 1} 条操作失败（{op_type}）：{exc}") from exc

    # 最后统一规范化：白名单过滤在这里兜底
    work = normalize_schema(work, registry)
    result.warnings = work.get("warnings", [])
    if dry_run:
        return result
    return result


# ---------------------------------------------------------------- 各操作实现

def _h_set_prop(schema: dict, op: dict, registry, kind: str) -> dict:
    node = _require_node(schema, op)
    key = op.get("prop")
    if not key:
        raise PatchError("缺少 prop 字段（要改哪个属性）")
    spec = registry.get(node["type"])
    props_spec = (spec.props_schema if spec else {}) or {}
    if props_spec and key not in props_spec:
        allowed = ", ".join(list(props_spec)[:8])
        raise PatchError(
            f"组件「{spec.name}」没有属性 '{key}'；可用属性：{allowed}"
            + ("…" if len(props_spec) > 8 else ""))
    if key not in ("url", "src", "href", "html") and op.get("value") is None:
        raise PatchError("value 不能为空（若要清空请传空字符串）")

    node.setdefault("props", {})[key] = op["value"]
    if op.get("note"):
        node["name"] = str(op["note"])[:64]
    return {"target": node["id"], "prop": key, "value": op["value"],
            "node_label": _label(node)}


def _h_set_style(schema: dict, op: dict, registry, kind: str) -> dict:
    node = _require_node(schema, op)
    key = str(op.get("style") or "")
    if not key:
        raise PatchError("缺少 style 字段（用下划线命名，如 background_color）")
    norm = key.replace("-", "_")
    if norm not in ALLOWED_STYLE_KEYS:
        near = [k for k in ALLOWED_STYLE_KEYS if norm[:4] in k][:4]
        hint = f"；你是否想用：{', '.join(near)}" if near else ""
        raise PatchError(f"不支持的样式 '{key}'（属性白名单限制）{hint}")
    if kind == "email" and norm in EMAIL_UNSAFE_STYLE_KEYS:
        raise PatchError(
            f"邮件不支持样式 '{key}'（Outlook 会忽略），请改用布局组件表达这个意图")
    value = op.get("value")
    node.setdefault("style", {})
    if value in (None, ""):
        node["style"].pop(norm, None)
    else:
        node["style"][norm] = str(value)
    return {"target": node["id"], "style": norm, "value": value,
            "node_label": _label(node)}


def _h_set_doc(schema: dict, op: dict, registry, kind: str) -> dict:
    key = op.get("field")
    if key not in _DOC_FIELDS:
        raise PatchError(f"field 必须是 {', '.join(sorted(_DOC_FIELDS))}")
    value = op.get("value")
    if value is None:
        raise PatchError("value 不能为空")
    value = str(value)
    limits = {"subject": 120, "preheader": 120, "name": 200, "description": 300,
              "key": 96, "locale": 12}
    if len(value) > limits.get(key, 300):
        raise PatchError(f"{key} 超过 {limits[key]} 字符（当前 {len(value)}）")
    if key == "locale" and not _is_locale(value):
        raise PatchError("locale 需形如 zh-CN / en-GB / en-US")
    schema.setdefault("doc", {})[key] = value
    return {"field": key, "value": value}


def _h_set_token(schema: dict, op: dict, registry, kind: str) -> dict:
    from ..render.theme import TOKEN_META
    key = op.get("token")
    if key not in TOKEN_META:
        near = [k for k in TOKEN_META if str(key)[:3] in k][:5]
        raise PatchError(
            f"未知 token '{key}'；可用 token：{', '.join(list(TOKEN_META)[:8])}…"
            + (f"（你可能想用 {', '.join(near)}）" if near else ""))
    value = op.get("value")
    if value in (None, ""):
        schema.setdefault("theme", {}).get("token_overrides", {}).pop(key, None)
        return {"token": key, "value": None, "action": "reset"}
    schema.setdefault("theme", {}).setdefault("token_overrides", {})[key] = str(value)
    return {"token": key, "value": str(value), "action": "set"}


def _h_add_block(schema: dict, op: dict, registry, kind: str) -> dict:
    block_type = op.get("type")
    spec = registry.get(block_type)
    if spec is None:
        raise PatchError(f"组件不存在：{block_type}")
    if kind not in spec.get("kind", []):
        raise PatchError(
            f"组件「{spec.name}」不能用于 {kind} 类型内容"
            f"（支持：{', '.join(spec.get('kind', []))}）")

    parent_id = op.get("parent_id") or schema.get("root", {}).get("id")
    parent = find_node(schema.get("root") or {}, parent_id) if parent_id else None
    if parent is None:
        raise PatchError(f"父节点不存在：{parent_id}")
    parent_spec = registry.get(parent["type"])
    if parent_spec and not parent_spec.get("container"):
        raise PatchError(f"「{parent_spec.name}」不是容器，不能往里放组件")
    allowed = parent_spec.get("children_allowed") if parent_spec else None
    if allowed and block_type not in allowed:
        raise PatchError(
            f"「{parent_spec.name}」只允许放入：{', '.join(allowed)}")
    maxn = (parent_spec.get("children_limit") or {}).get("max") if parent_spec else None
    if maxn and len(parent.get("children") or []) >= maxn:
        raise PatchError(f"「{parent_spec.name}」最多 {maxn} 个子组件")

    node = spec.make(op.get("props") or {}, node_id=op.get("id") or new_id("b"))
    node["style"] = {k: str(v) for k, v in (op.get("style") or {}).items()
                     if k.replace("-", "_") in ALLOWED_STYLE_KEYS}
    parent.setdefault("children", []).append(node)
    return {"type": block_type, "new_id": node["id"], "parent_id": parent["id"],
            "node_label": _label(node)}


def _h_remove(schema: dict, op: dict, registry, kind: str) -> dict:
    node = _require_node(schema, op)
    root = schema.get("root") or {}
    if node["id"] == root.get("id"):
        raise PatchError("不能删除根节点")
    parent = find_parent(root, node["id"])
    if parent is None:
        raise PatchError(f"节点不在树中：{node['id']}")
    n_children = len(parent.get("children") or [])
    parent["children"] = [c for c in parent["children"] if c.get("id") != node["id"]]
    return {"target": node["id"], "node_label": _label(node),
            "sibling_count": n_children}


def _h_move(schema: dict, op: dict, registry, kind: str) -> dict:
    node = _require_node(schema, op)
    root = schema.get("root") or {}
    if node["id"] == root.get("id"):
        raise PatchError("不能移动根节点")
    new_parent_id = op.get("parent_id") or root.get("id")
    new_parent = find_node(root, new_parent_id)
    if new_parent is None:
        raise PatchError(f"目标父节点不存在：{new_parent_id}")
    # 防循环：不能移动到自己的子树里
    inside = False
    walk(node, lambda n, _p: inside or n.get("id") == new_parent_id)
    if inside:
        raise PatchError("不能把组件移动到它自己的子节点里")
    parent_spec = registry.get(new_parent["type"])
    if parent_spec and not parent_spec.get("container"):
        raise PatchError(f"「{parent_spec.name}」不是容器")
    allowed = parent_spec.get("children_allowed") if parent_spec else None
    if allowed and node["type"] not in allowed:
        raise PatchError(
            f"「{parent_spec.name}」只允许放入：{', '.join(allowed)}")

    old_parent = find_parent(root, node["id"])
    if old_parent is None:
        raise PatchError("节点不在树中")
    old_parent["children"] = [c for c in old_parent["children"]
                              if c.get("id") != node["id"]]
    kids = new_parent.setdefault("children", [])
    index = op.get("index")
    if index is None:
        kids.append(node)
    else:
        try:
            kids.insert(max(0, min(int(index), len(kids))), node)
        except (TypeError, ValueError):
            raise PatchError(f"index 必须是整数，当前 {index!r}") from None
    return {"target": node["id"], "new_parent_id": new_parent["id"],
            "index": index, "node_label": _label(node)}


def _h_set_hidden(schema: dict, op: dict, registry, kind: str) -> dict:
    node = _require_node(schema, op)
    hidden = op.get("hidden")
    if hidden is None:
        hidden = not node.get("hidden", False)
    node["hidden"] = bool(hidden)
    return {"target": node["id"], "hidden": bool(hidden),
            "node_label": _label(node)}


_HANDLERS = {
    "set_prop": _h_set_prop,
    "set_style": _h_set_style,
    "set_doc": _h_set_doc,
    "set_token": _h_set_token,
    "add_block": _h_add_block,
    "remove": _h_remove,
    "move": _h_move,
    "set_hidden": _h_set_hidden,
}


def _require_node(schema: dict, op: dict) -> dict:
    nid = op.get("target") or op.get("id")
    if not nid:
        raise PatchError("缺少 target 字段（要改哪个组件的 id）")
    node = find_node(schema.get("root") or {}, nid)
    if node is None:
        raise PatchError(f"组件不存在：{nid}")
    return node


def _label(node: dict) -> str:
    p = node.get("props") or {}
    raw = (p.get("text") or p.get("label") or p.get("title") or p.get("name")
           or p.get("form_name") or "")
    import re
    text = re.sub(r"<[^>]+>", " ", str(raw)).strip()
    return (text[:36] or node.get("type", ""))


def outline_index(schema: dict) -> list[dict]:
    """给 AI 用的组件清单：id + 类型 + 可读标签 + 关键 props。

    让模型能"看着清单说人话"，比让它凭空猜 id 靠谱得多。
    """
    out: list[dict] = []

    def walk(node: dict, depth: int = 0, path: str = "") -> None:
        if node.get("type", "").endswith(".root"):
            for ch in node.get("children") or []:
                walk(ch, depth, path)
            return
        p = node.get("props") or {}
        spec_hint = _label(node)
        entry = {
            "id": node.get("id"),
            "type": node.get("type"),
            "label": spec_hint,
            "depth": depth,
            "path": f"{path}/{spec_hint}"[:80],
        }
        # 只带少量关键属性，避免 token 爆炸
        keys = [k for k in ("text", "title", "url", "name", "label", "subject")
                if p.get(k)]
        if keys:
            entry["props"] = {k: str(p[k])[:60] for k in keys}
        out.append(entry)
        for i, ch in enumerate(node.get("children") or []):
            walk(ch, depth + 1, f"{path}/{spec_hint}[{i}]" if spec_hint else path)

    walk(schema.get("root") or {})
    return out