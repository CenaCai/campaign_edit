"""渲染分发：按 kind 选渲染器，并暴露 preview / export 两种模式。"""
from __future__ import annotations

from typing import Any

from ..models import ContentKind
from . import email as _email
from . import form as _form
from . import landing as _landing
from . import lint as _lint
from .theme import merge_tokens

RENDERERS = {
    ContentKind.EMAIL: _email.EmailRenderer,
    ContentKind.FORM: _form.FormRenderer,
    ContentKind.LANDING: _landing.LandingRenderer,
}


def resolve_tokens(schema: dict, extra: dict | None = None) -> dict[str, str]:
    theme = (schema or {}).get("theme") or {}
    return merge_tokens(extra, theme.get("token_overrides") or {})


def render(schema: dict, *, kind: str | None = None, tokens: dict | None = None,
           **kw) -> str:
    kind = kind or (schema or {}).get("kind")
    cls = RENDERERS.get(kind)
    if cls is None:
        raise ValueError(f"未知内容类型: {kind}")
    return cls(tokens or resolve_tokens(schema)).render(schema, **kw)


def preview(schema: dict, *, kind: str | None = None, tokens: dict | None = None) -> dict:
    """编辑器实时预览：HTML + lint 结果 + 提取到的结构信息。"""
    kind = kind or schema.get("kind")
    tokens = tokens or resolve_tokens(schema)
    html = render(schema, kind=kind, tokens=tokens)
    info = extract_info(schema)
    lint = _lint.lint(schema, html) if kind == ContentKind.EMAIL else _lint.lint_generic(schema, html)
    return {"kind": kind, "html": html, "lint": lint, "info": info}


def extract_info(schema: dict) -> dict[str, Any]:
    """从 schema 抽取结构摘要（列表页、导出面板、handover 用）。"""
    doc = schema.get("doc") or {}
    root = schema.get("root") or {}
    blocks: list[dict] = []
    total_chars = 0
    links: list[str] = []

    def walk(node: dict, depth: int = 0) -> None:
        nonlocal total_chars
        p = node.get("props") or {}
        ntype = node.get("type", "")
        label = p.get("text") or p.get("title") or p.get("label") or p.get("name") or ntype
        blocks.append({"id": node.get("id"), "type": ntype, "depth": depth,
                       "label": str(label)[:60]})
        for key in ("html", "desc", "title", "text", "value"):
            if isinstance(p.get(key), str):
                total_chars += len(p[key])
        for key in ("url", "href", "src"):
            if p.get(key):
                links.append(str(p[key]))
        for ch in node.get("children") or []:
            walk(ch, depth + 1)

    walk(root)
    return {
        "name": doc.get("name") or "",
        "subject": doc.get("subject") or "",
        "preheader": doc.get("preheader") or "",
        "locale": doc.get("locale") or "zh-CN",
        "block_count": len(blocks),
        "text_chars": total_chars,
        "link_count": len({l for l in links if l}),
        "blocks": blocks,
    }