"""Block Schema —— 全链路唯一数据契约。

意图识别 → 模板 → 编辑器 → 渲染 → 导出 → Mautic 投递，全部围绕这一份 JSON。

    {
      "schema_version": "1.0",
      "kind": "email" | "form" | "landing",
      "doc":   { "key","name","locale","subject","preheader","description","project_key" },
      "theme": { "theme_id": "...", "token_overrides": {"--brand": "#c8102e"} },
      "root":  { "id":"root", "type":"...", "props":{}, "style":{}, "children":[ BlockNode ] }
    }

BlockNode:
    { "id": "b_xxx", "type": "hero.banner", "props": {...}, "style": {...},
      "children": [...], "behaviors": { "showIf": {...} } }

设计约束（刻意为之，便于多人协作与稳定导出）：
* props 只允许出现在组件 ``props_schema`` 声明过的字段，未知键在保存时被规范化剔除。
* style 只允许白名单的 CSS 属性子集（见 ``ALLOWED_STYLE_KEYS``），email 额外禁外部/高级属性。
* 节点 id 全局唯一且稳定，评论锚点、diff、协作锁都依赖它。
"""
from __future__ import annotations

import copy
import re
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"

# 允许出现在 style 里的 CSS 属性子集。刻意保守：只留跨编辑器可移植的那部分。
ALLOWED_STYLE_KEYS = {
    "display", "width", "max_width", "min_height", "height",
    "margin", "margin_top", "margin_bottom", "margin_left", "margin_right",
    "padding", "padding_top", "padding_bottom", "padding_left", "padding_right",
    "background", "background_color", "background_image", "background_size",
    "background_position", "background_repeat", "border", "border_radius",
    "border_color", "border_width", "border_style", "box_shadow",
    "color", "font_size", "font_weight", "font_family", "line_height",
    "letter_spacing", "text_align", "text_transform", "text_decoration",
    "vertical_align", "opacity", "overflow", "position", "top", "left", "gap",
    "flex_direction", "justify_content", "align_items", "flex_wrap",
}
# email 渲染中禁用的（Outlook/各家客户端支持极差）
EMAIL_UNSAFE_STYLE_KEYS = {"position", "top", "left", "gap", "flex_direction", "justify_content",
                           "align_items", "flex_wrap", "min_height", "box_shadow", "overflow"}

_ID_RE = re.compile(r"^[a-zA-Z0-9_:.\-]{1,64}$")


def _blank_props(spec: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, meta in (spec or {}).items():
        if not isinstance(meta, dict):
            continue
        if "default" in meta:
            out[key] = copy.deepcopy(meta["default"])
        elif meta.get("type") == "object":
            out[key] = _blank_props(meta.get("props", {}))
        elif meta.get("type") == "array":
            out[key] = copy.deepcopy(meta.get("default", []))
        else:
            out[key] = _zero(meta.get("type", "string"))
    return out


def _zero(t: str) -> Any:
    return {"number": 0, "boolean": False, "array": [], "object": {}}.get(t, "")


def new_id(prefix: str = "b") -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class SchemaError(ValueError):
    """Schema 不合法。"""


def walk(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """深度优先遍历（含自身）。"""
    yield node
    for ch in node.get("children") or []:
        if isinstance(ch, dict):
            yield from walk(ch)


def find_node(root: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for n in walk(root):
        if n.get("id") == node_id:
            return n
    return None


def find_parent(root: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    for n in walk(root):
        for ch in n.get("children") or []:
            if isinstance(ch, dict) and ch.get("id") == node_id:
                return n
    return None


def make_node(block_type: str, props: dict | None = None, *, spec: dict | None = None,
              node_id: str | None = None) -> dict[str, Any]:
    """按组件定义创建节点（缺省 props 由 props_schema 填充）。"""
    if spec:
        merged = _blank_props(spec.get("props_schema"))
        merged.update(props or {})
        resolved = props
    else:
        resolved, merged = props, copy.deepcopy(props or {})
    return {
        "id": node_id or new_id(),
        "type": block_type,
        "props": merged,
        "style": {},
        "children": [],
        "resolved_props": resolved,
    }


def normalize_style(style: dict | None, *, email: bool = False) -> dict[str, Any]:
    """白名单过滤；email 模式额外剔除不安全属性。"""
    out: dict[str, Any] = {}
    for k, v in (style or {}).items():
        k = (k or "").strip()
        if k not in ALLOWED_STYLE_KEYS or v in (None, ""):
            continue
        if email and k in EMAIL_UNSAFE_STYLE_KEYS:
            continue
        out[k] = v
    return out


def normalize_node(node: dict[str, Any], spec: dict[str, Any], *, email: bool = False) -> dict[str, Any]:
    """按组件定义规范化单个节点（剔除未知 props、过滤 style、校验必填）。"""
    if not isinstance(node, dict):
        raise SchemaError("节点必须是对象")
    ntype = node.get("type")
    if ntype != spec.get("key"):
        raise SchemaError(f"组件类型不匹配：期望 {spec.get('key')}，实际 {ntype}")
    nid = node.get("id") or new_id()
    if not _ID_RE.match(nid):
        raise SchemaError(f"非法节点 id: {nid}")

    props_spec = spec.get("props_schema") or {}
    raw_props = node.get("props") or {}
    props: dict[str, Any] = _blank_props(props_spec)
    for k, v in raw_props.items():
        if k in props_spec:
            props[k] = v

    # 必填 + 枚举校验
    for k, meta in props_spec.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("required") and props.get(k) in (None, "", [], {}):
            props[k] = meta.get("default", props.get(k))
        if meta.get("enum") and props.get(k) not in meta["enum"] and props.get(k) != "":
            props[k] = meta.get("default", meta["enum"][0])

    out: dict[str, Any] = {
        "id": nid,
        "type": ntype,
        "props": props,
        "style": normalize_style(node.get("style"), email=email),
    }
    if spec.get("container"):
        allowed = spec.get("children_allowed")
        kids: list[dict[str, Any]] = []
        for ch in node.get("children") or []:
            if not isinstance(ch, dict):
                continue
            if allowed and ch.get("type") not in allowed:
                continue
            kids.append(ch)  # 递归规范化交给上层按 registry 处理
        limit = (spec.get("children_limit") or {}).get("max")
        if limit:
            kids = kids[: int(limit)]
        out["children"] = kids
    else:
        out["children"] = []

    if node.get("behaviors"):
        out["behaviors"] = copy.deepcopy(node["behaviors"])
    if node.get("name"):
        out["name"] = str(node["name"])[:64]
    if node.get("hidden"):
        out["hidden"] = True
    return out


def normalize_schema(schema: dict[str, Any], registry) -> dict[str, Any]:
    """整体规范化：doc/theme 补齐 + 递归规范化每个节点 + 收集警告。"""
    warnings: list[str] = []
    if not isinstance(schema, dict):
        raise SchemaError("schema 必须是对象")
    kind = schema.get("kind")
    if kind not in ("email", "form", "landing"):
        raise SchemaError(f"kind 不合法: {kind}")

    doc = copy.deepcopy(schema.get("doc") or {})
    doc.setdefault("locale", "zh-CN")
    doc.setdefault("name", "未命名内容")
    doc.setdefault("key", "")
    doc.setdefault("subject", "")
    doc.setdefault("preheader", "")
    doc.setdefault("description", "")

    theme = copy.deepcopy(schema.get("theme") or {})
    theme.setdefault("theme_id", "")
    theme.setdefault("token_overrides", {})

    email = kind == "email"
    root_raw = schema.get("root")
    root_spec = registry.root_spec(kind)
    if not isinstance(root_raw, dict):
        raise SchemaError("root 必须是对象")
    root = normalize_node(root_raw, root_spec, email=email)

    # 递归规范化子节点。注意：必须先算出新节点再写回，
    # 不能就地 clear()——那会把type/props 一起抹掉。
    def fix_children(node: dict[str, Any]) -> None:
        kept: list[dict[str, Any]] = []
        for ch in node.get("children") or []:
            if not isinstance(ch, dict):
                continue
            spec = registry.get(ch.get("type"))
            if spec is None:
                warnings.append(f"未知组件 {ch.get('type')}，已移除")
                continue
            normalized_child = normalize_node(ch, spec, email=email)
            fix_children(normalized_child)
            kept.append(normalized_child)
        node["children"] = kept

    fix_children(root)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "doc": doc,
        "theme": theme,
        "root": root,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- diff

def diff_nodes(old: dict[str, Any] | None, new: dict[str, Any] | None, path: str = "root") -> list[dict]:
    """schema 级结构化 diff（供版本对比 UI 使用，不依赖第三方库）。"""
    if old is None and new is not None:
        return [{"op": "add", "path": path, "type": (new or {}).get("type")}]
    if new is None and old is not None:
        return [{"op": "remove", "path": path, "type": (old or {}).get("type")}]
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [] if old == new else [{"op": "replace", "path": path, "old": old, "new": new}]

    out: list[dict] = []
    if old.get("id") and new.get("id") and old["id"] != new["id"]:
        out.append({"op": "move", "path": path, "old": old["id"], "new": new["id"]})
    if old.get("type") != new.get("type"):
        out.append({"op": "type_change", "path": path, "old": old.get("type"), "new": new.get("type")})
    for key in ("props", "style"):
        a, b = old.get(key) or {}, new.get(key) or {}
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                out.append({"op": "replace", "path": f"{path}.{key}.{k}", "old": a.get(k), "new": b.get(k)})
    old_kids = {c.get("id"): c for c in (old.get("children") or []) if isinstance(c, dict)}
    new_kids = {c.get("id"): c for c in (new.get("children") or []) if isinstance(c, dict)}
    for cid, c in old_kids.items():
        if cid not in new_kids:
            out.append({"op": "remove", "path": f"{path}#{cid}", "type": c.get("type")})
    for cid, c in new_kids.items():
        if cid not in old_kids:
            out.append({"op": "add", "path": f"{path}#{cid}", "type": c.get("type")})
        else:
            out.extend(diff_nodes(old_kids[cid], c, path=f"{path}#{cid}"))
    if old_kids and new_kids and list(old_kids) != list(new_kids):
        out.append({"op": "reorder", "path": path,
                    "old": list(old_kids), "new": list(new_kids)})
    return out


def schema_diff(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    changes = diff_nodes((old or {}).get("root"), (new or {}).get("root")) if (old or new) else []
    summary: dict[str, int] = {}
    for c in changes:
        summary[c["op"]] = summary.get(c["op"], 0) + 1
    return {"summary": summary, "changes": changes[:2000]}