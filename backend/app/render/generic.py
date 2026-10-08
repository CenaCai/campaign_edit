"""通用渲染器：给插件组件复用的兜底实现。

插件组件通过 ``renderer: generic_*`` 复用这些函数，因此不需要在插件里放代码。
新增自定义渲染逻辑时，在这里加函数 + 更新 manifest 白名单（走代码评审）。
"""
from __future__ import annotations

from typing import Any

from .common import esc, slugify, style_str, with_utm
from .theme import merge_tokens


class GenericRenderer:
    """按 props/schema 通用渲染：text / html / image / button / spacer / field。"""

    kind = "generic"

    def __init__(self, tokens: dict | None = None) -> None:
        self.t = merge_tokens(tokens)

    def render(self, schema: dict, **_: Any) -> str:
        root = schema.get("root") or {}
        return self._children(root, top=True)

    def _children(self, node: dict, *, top: bool = False) -> str:
        return "".join(self.node(c) for c in (node.get("children") or []) if not c.get("hidden"))

    def node(self, node: dict) -> str:
        kind = node.get("type", "").split(".")[0]
        fn = {"email": self.email_block, "form": self.form_block,
              "landing": self.landing_block}.get(kind)
        if fn is None:
            return ""
        return fn(node)

    # -------------------------------------------------- 通用入口
    def _dispatch(self, node: dict, tag: str) -> str:
        renderer = (node.get("_renderer") or "").strip()
        p = node.get("props") or {}
        st = node.get("style") or {}
        style = style_str(st)
        if renderer == "generic_spacer":
            return f'<div style="height:{esc(p.get("height") or 32)}px"></div>'
        if renderer == "generic_image" or (renderer == "" and p.get("src")):
            img = (f'<img src="{esc(p.get("src"))}" alt="{esc(p.get("alt") or "")}" '
                   f'style="{style}width:100%;display:block">')
            if p.get("href"):
                return f'<a href="{esc(p["href"])}">{img}</a>'
            return img
        if renderer in ("generic_button", "generic_html") or p.get("url"):
            label = p.get("text") or p.get("label") or ""
            url = with_utm(str(p.get("url") or "#"), str(p.get("utm_params") or ""))
            extra = style_str({"color": p.get("color") or "", "font_size": p.get("font_size") or ""})
            merged = (style + ";" + extra).strip(";")
            return (f'<a href="{esc(url)}" style="{merged}" '
                    f'data-track="cta">{esc(label)}</a>')
        # 默认：文本
        text = p.get("html") or p.get("text") or p.get("label") or ""
        extra = style_str({"color": p.get("color") or "", "font_size": p.get("font_size") or "",
                           "font-weight": p.get("font_weight") or ""})
        merged = (style + ";" + extra).strip(";")
        if not text:
            return ""
        if "<" in str(text):
            return f'<div style="{merged}">{text}</div>'
        return f'<{tag} style="{merged}">{esc(text)}</{tag}>'

    # -------------------------------------------------- 分类型
    def email_block(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        style = style_str(st)
        extra = style_str({"color": p.get("color") or "",
                           "font-size": p.get("font_size") or "",
                           "text-align": p.get("align") or ""})
        merged = (style + ";" + extra).strip(";")
        content = p.get("html") or p.get("text") or ""
        return (f'<tr><td style="{merged};padding:12px 16px">'
                f'<div style="{merged}">{content if "<" in str(content) else esc(content)}</div>'
                f'</td></tr>')

    def form_block(self, node: dict) -> str:
        p = node.get("props") or {}
        name = esc(p.get("name") or p.get("label") or "field")
        fid = f"cf-{slugify(p.get('name') or node.get('id') or 'field')}"
        req = " required" if p.get("required") else ""
        label = esc(p.get("label") or p.get("name") or "")
        itype = p.get("input_type") or "text"
        star = '<span style="color:#e5484d">*</span>' if p.get("required") else ""
        return (f'<div class="ce-field" data-field="{name}">'
                f'<label class="ce-label" for="{fid}">{label}{star}</label>'
                f'<input id="{fid}" class="ce-input" type="{esc(itype)}" name="{name}" '
                f'placeholder="{esc(p.get("placeholder") or "")}"{req}>'
                f'<p class="ce-error" role="alert" hidden></p></div>')

    def landing_block(self, node: dict) -> str:
        return self._dispatch(node, "div")


def render_generic(schema: dict, tokens: dict | None = None, **kw) -> str:
    return GenericRenderer(tokens).render(schema, **kw)