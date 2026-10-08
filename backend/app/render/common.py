"""共享渲染工具：HTML 转义、style 序列化、UTM 拼装、响应式属性。"""
from __future__ import annotations

import html as _html
import re
import urllib.parse
from typing import Any

_SAFE_STYLE_KEYS_ORDER = [
    "display", "position", "top", "left", "width", "max-width", "min-height", "height",
    "margin", "margin-top", "margin-bottom", "margin-left", "margin-right",
    "padding", "padding-top", "padding-bottom", "padding-left", "padding-right",
    "background", "background-color", "background-image", "background-size",
    "background-position", "background-repeat", "border", "border-radius", "border-color",
    "border-width", "border-style", "box-shadow", "color", "font-family", "font-size",
    "font-weight", "line-height", "letter-spacing", "text-align", "text-transform",
    "text-decoration", "vertical-align", "opacity", "overflow", "gap",
    "flex-direction", "justify-content", "align-items", "flex-wrap",
]


def esc(v: Any) -> str:
    return _html.escape(str(v if v is not None else ""), quote=True)


def kebab(key: str) -> str:
    return key.replace("_", "-")


def style_str(style: dict[str, Any] | None, *, order: list[str] | None = None) -> str:
    """把 schema.style 序列化为 CSS 字符串，顺序稳定（便于 diff 与快照测试）。"""
    if not style:
        return ""
    order = order or _SAFE_STYLE_KEYS_ORDER
    keys = [k for k in order if k in style]
    keys += [k for k in style if k not in order]
    parts = []
    for k in keys:
        v = style.get(k)
        if v in (None, ""):
            continue
        parts.append(f"{kebab(k)}:{v}")
    return ";".join(parts)


def block_style(node: dict, *, extra: dict | None = None) -> str:
    """组件 style + style_defaults + 传入的 props 派生样式 合并。"""
    merged: dict[str, Any] = {}
    merged.update(node.get("style") or {})
    merged.update({k: v for k, v in (extra or {}).items() if v not in (None, "")})
    return style_str(merged)


def props_style(props: dict, mapping: dict[str, tuple[str, Any]]) -> dict[str, Any]:
    """props → style 的显式映射表。key 是 props 名，value 是 (css key, 固定值或 None)。"""
    out: dict[str, Any] = {}
    for pname, (css_key, const) in mapping.items():
        v = props.get(pname)
        if v in (None, ""):
            continue
        out[css_key] = const if const is not None else v
    return out


def with_utm(url: str, utm: str) -> str:
    """给链接追加 UTM 参数（utm 形如 a=b&c=d）。"""
    if not url or not utm:
        return url
    if url.startswith("#") or url.startswith("mailto:") or url.startswith("tel:"):
        return url
    joiner = "&" if "?" in url else "?"
    extra = utm if utm.startswith(("?", "&")) else utm.lstrip("?&")
    return f"{url}{joiner}{extra}" if extra else url


_TRACK_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")


def strip_tracking(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    if not p.query:
        return url
    qs = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
          if k not in _TRACK_PARAMS]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path,
                                    urllib.parse.urlencode(qs), p.fragment))


_TAG_RE = re.compile(r"<[^>]+>")


def plain_text(html_str: str, limit: int = 0) -> str:
    t = re.sub(r"\s+", " ", _TAG_RE.sub(" ", html_str or "")).strip()
    if limit and len(t) > limit:
        t = t[:limit].rstrip() + "…"
    return t


def slugify(name: str, fallback: str = "item") -> str:
    s = re.sub(r"[^\w一-鿿-]+", "-", (name or "").strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or fallback


def pad2(n: int) -> str:
    return f"{n:02d}"


def split_box_shadow(shadow: str) -> tuple[str, int]:
    m = re.search(r"(\d+)px\s+(?:(\d+)px\s+)?(?:rgba?\([^)]*\)|\w+)", shadow or "")
    return (shadow or "none", int(m.group(1)) if m else 0)


def css_custom_properties(tokens: dict[str, str]) -> str:
    return ";".join(f"--{k}:{v}" for k, v in tokens.items())