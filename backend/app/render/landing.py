"""着陆页 / 营销活动站点渲染器。

产物三种形态
------------
* ``full_page``  ：单文件 HTML（内联 CSS + 少量 JS），可直接投放/邮件内嵌/上传即用；
* ``section``    ：仅区块 HTML，用于嵌入已有站点或拼装（配合多页导出）；
* ``bundle``     ：交由 export/scaffold.py 产出多文件工程。

硬约束：SSR 直出 HTML（无 JS 也能读全文与所有 CTA），JS 只做倒计时、FAQ、粘性导航等增强。
"""
from __future__ import annotations

import re
from typing import Any

from .common import esc, slugify, style_str, with_utm
from .theme import merge_tokens

_SECTION_RANK = ["hero", "layout", "text", "media", "action", "commerce", "trust",
                 "social", "form", "basic"]


def _t(tokens: dict, key: str) -> str:
    return str(tokens.get(key, ""))


_SAFE_CSS_URL = re.compile(r"url\((?!\s*['\"]?\s*(javascript|data|vbscript):)[^)]+\)", re.I)
_BAD_CSS = re.compile(r"(expression\s*\(|javascript:|@import)", re.I)


def _clean_css(css: str) -> str:
    css = _BAD_CSS.sub("", css or "")
    return _SAFE_CSS_URL.sub("url('')", css)


def _clean_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return "#"
    if re.match(r"^\s*(javascript|vbscript|data):", u, re.I):
        return "#"
    if u.startswith(("#", "mailto:", "tel:")):
        return u
    if u.startswith("//"):
        return "https:" + u
    if not re.match(r"^https?://", u, re.I):
        return "https://" + u.lstrip("/")
    return u


def _sorted_children(node: dict) -> list[dict]:
    kids = [k for k in (node.get("children") or []) if not k.get("hidden")]
    return kids


class LandingRenderer:
    kind = "landing"

    def __init__(self, tokens: dict | None = None) -> None:
        self.t = merge_tokens(tokens)

    # -------------------------------------------------- 主入口
    def render(self, schema: dict, *, mode: str = "full_page",
               inline_css: bool = True, with_js: bool = True) -> str:
        root = schema.get("root") or {}
        doc = schema.get("doc") or {}
        body = self._children_html(root, root_level=True)

        if mode == "section":
            return body

        p = root.get("props") or {}
        width = p.get("content_width") or _t(self.t, "container_width")
        font = p.get("font_family") or _t(self.t, "font_family")
        bg = p.get("bg_color") or _t(self.t, "bg")
        lang = p.get("lang") or doc.get("locale") or "zh-CN"
        title = doc.get("name") or "Campaign"
        desc = doc.get("description") or ""
        css = self._css(width, font, bg)

        head = [
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
            f"<title>{esc(title)}</title>",
        ]
        if desc:
            head.append(f'<meta name="description" content="{esc(desc[:180])}">')
            head.append(f'<meta property="og:description" content="{esc(desc[:180])}">')
        head.append(f'<meta property="og:title" content="{esc(title)}">')
        head.append(f'<meta property="og:type" content="website">')
        head.append('<meta name="theme-color" '
                    f'content="{esc(_t(self.t, "secondary"))}">')
        if inline_css:
            head.append(f"<style>{css}</style>")
        js = f"<script>{self._js()}</script>" if with_js else ""
        return (f'<!DOCTYPE html>\n<html lang="{esc(lang)}">\n<head>\n' + "\n".join(head)
                + f"\n</head>\n<body>\n{body}\n{js}\n</body>\n</html>")

    # -------------------------------------------------- 遍历
    def _children_html(self, node: dict, *, root_level: bool = False) -> str:
        parts = []
        for ch in _sorted_children(node):
            fn = getattr(self, f"r_{ch.get('type','').replace('.', '_')}", None)
            if fn:
                parts.append(fn(ch))
        return "\n".join(p for p in parts if p)

    def _section_wrap(self, node: dict, inner: str, *, extra_class: str = "") -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        bg = st.get("background_color") or p.get("bg_color") or "transparent"
        pt = int(p.get("pad_top") or 64)
        pb = int(p.get("pad_bottom") or 64)
        if st.get("padding"):
            pt, pb = None, None
        pad = st.get("padding") or f"{pt}px 20px {pb}px 20px"
        anchor = p.get("anchor") or ""
        id_attr = f' id="{esc(anchor)}"' if anchor else ""
        cls = f"ce-section {extra_class}".strip()
        bg_image = ""
        if p.get("bg_image"):
            bg_image = (f"background-image:url('{esc(_clean_url(p['bg_image']))}');"
                        "background-size:cover;background-position:center;")
        style = style_str({"padding": pad, "background-color": bg, "background-image": bg_image})
        return f'<section{ id_attr } class="{cls}" style="{style}">{inner}</section>'

    def _container(self, inner: str, width: str | None = None) -> str:
        return (f'<div class="ce-container" style="max-width:{esc(width or _t(self.t, "container_width"))}'
                f';margin:0 auto">{inner}</div>')

    # -------------------------------------------------- 组件
    def r_landing_root(self, node: dict) -> str:
        st = node.get("style") or {}
        bg = st.get("background_color") or (node.get("props") or {}).get("bg_color") or _t(self.t, "bg")
        font = (node.get("props") or {}).get("font_family") or _t(self.t, "font_family")
        style = style_str({"background-color": bg, "font-family": font, "color": _t(self.t, "text")})
        return f'<div class="ce-page" style="{style}">{self._children_html(node, root_level=True)}</div>'

    def r_landing_nav(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        bg = st.get("background_color") or p.get("bg_color") or _t(self.t, "bg")
        sticky = " ce-sticky" if p.get("sticky") else ""
        logo = ""
        if p.get("logo_image"):
            logo = (f'<img src="{esc(_clean_url(p["logo_image"]))}" '
                    f'alt="{esc(p.get("logo_text") or "Logo")}" style="height:32px">')
        elif p.get("logo_text"):
            logo = (f'<span class="ce-logo">{esc(p["logo_text"])}</span>')
        links = "".join(
            f'<a class="ce-nav-link" href="{esc(_clean_url(l.get("href")))}">{esc(l.get("label"))}</a>'
            for l in (p.get("links") or []) if isinstance(l, dict))
        extra = self._children_html(node)
        style = style_str({"background-color": bg, "padding": st.get("padding") or "16px 20px"})
        return (f'<nav class="ce-nav{sticky}" style="{style}">'
                f'<div class="ce-container ce-nav-inner">{logo}'
                f'<div class="ce-nav-links">{links}</div>{extra}</div></nav>')

    def r_landing_hero(self, node: dict) -> str:
        p = node.get("props") or {}
        inner = self._children_html(node)
        layout = p.get("layout", "centered")
        min_h = p.get("min_height") or "480px"
        overlay = ""
        if p.get("overlay"):
            overlay = (f'position:absolute;inset:0;background:'
                      f'{esc(p.get("overlay_color") or "rgba(0,0,0,0.45)")};')
        cls = "ce-hero ce-hero-split" if layout == "split" else "ce-hero ce-hero-centered"
        wrap = (f'<div class="{cls}" style="position:relative;min-height:{esc(min_h)};'
                f'display:flex;align-items:center">'
                f'<div class="ce-hero-overlay" style="{overlay}"></div>'
                f'<div class="ce-container ce-hero-inner" style="position:relative;z-index:1;'
                f'width:100%">{inner}</div></div>')
        return self._section_wrap(node, wrap, extra_class="ce-section-hero")

    def r_landing_section(self, node: dict) -> str:
        inner = self._children_html(node)
        if not inner:
            return ""
        p = node.get("props") or {}
        if p.get("container", True):
            inner = self._container(inner)
        return self._section_wrap(node, inner)

    def r_landing_heading(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        lvl = p.get("level", "h2")
        sizes = {"h1": "clamp(28px,5vw,52px)", "h2": "clamp(22px,3.4vw,36px)",
                 "h3": "clamp(18px,2.4vw,26px)", "h4": "20px"}
        style = style_str({
            "font-size": st.get("font_size") or sizes.get(lvl, "clamp(22px,3.4vw,36px)"),
            "color": st.get("color") or p.get("color") or _t(self.t, "secondary"),
            "text-align": p.get("align", "left"),
            "max-width": p.get("max_width") or "none",
            "line-height": "1.25", "margin": "0 0 16px", "font-weight": "800",
        })
        return f'<{lvl} class="ce-h" style="{style}">{esc(p.get("text") or "")}</{lvl}>'

    def r_landing_text(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        style = style_str({
            "text-align": p.get("align", "left"),
            "color": st.get("color") or p.get("color") or "",
            "font-size": p.get("font_size") or _t(self.t, "font_size_base"),
            "max-width": p.get("max_width") or "none",
            "line-height": _t(self.t, "line_height"), "margin": "0 0 16px",
        })
        return f'<div class="ce-p" style="{style}">{_sanitize_html(p.get("html") or "")}</div>'

    def r_landing_image(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        ratio = p.get("ratio", "auto")
        wrap_style = style_str({
            "border-radius": st.get("border_radius") or _t(self.t, "radius"),
            "overflow": "hidden", "background-color": _t(self.t, "bg_subtle"),
        })
        img_style = style_str({
            "width": st.get("width") or p.get("width") or "100%",
            "display": "block", "aspect-ratio": ratio.replace(":", " / ") if ratio != "auto" else "",
            "object-fit": "cover" if ratio != "auto" else "",
        })
        return (f'<figure class="ce-img" style="{wrap_style}">'
                f'<img src="{esc(_clean_url(p.get("src") or ""))}" '
                f'alt="{esc(p.get("alt") or "")}" loading="{esc(p.get("loading") or "lazy")}" '
                f'style="{img_style}"></figure>')

    def r_landing_video(self, node: dict) -> str:
        p = node.get("props") or {}
        if not p.get("embed_url"):
            return ""
        autoplay = "autoplay;" if p.get("autoplay") else ""
        loop = "loop;" if p.get("loop") else ""
        poster = (f' poster="{esc(_clean_url(p["poster"]))}"' if p.get("poster") else "")
        return (f'<div class="ce-video" style="border-radius:{_t(self.t,"radius")};overflow:hidden">'
                f'<iframe src="{esc(_clean_url(p["embed_url"]))}" '
                f'style="width:100%;aspect-ratio:16/9;border:0" allowfullscreen '
                f'allow="autoplay;fullscreen;picture-in-picture"{poster} '
                f'title="{esc(p.get("title") or "video")}"></iframe></div>'
                f'<!-- autoplay:{autoplay or "no"} loop:{loop or "no"} -->')

    def r_landing_button(self, node: dict) -> str:
        p = node.get("props") or {}
        variant = p.get("variant", "primary")
        url = with_utm(_clean_url(p.get("url") or "#"), p.get("utm_params") or "")
        size = p.get("size", "md")
        pad = {"sm": "8px 16px", "md": "12px 28px", "lg": "16px 40px"}[size]
        fs = {"sm": "14px", "md": "16px", "lg": "18px"}[size]
        if variant == "primary":
            style = style_str({"background-color": _t(self.t, "brand"),
                               "color": "#ffffff", "padding": pad, "font-size": fs,
                               "border-radius": _t(self.t, "radius_pill")})
        elif variant == "secondary":
            style = style_str({"background-color": _t(self.t, "secondary"),
                               "color": "#ffffff", "padding": pad, "font-size": fs,
                               "border-radius": _t(self.t, "radius_pill")})
        elif variant == "ghost":
            style = style_str({"border": f"2px solid {_t(self.t,'brand')}",
                               "color": _t(self.t, "brand"), "padding": pad,
                               "font-size": fs, "border-radius": _t(self.t, "radius_pill")})
        else:
            style = style_str({"color": _t(self.t, "brand"), "font-size": fs,
                               "text-decoration": "underline", "padding": "8px 0"})
        track = ' data-track="cta"' if p.get("track", True) else ""
        return (f'<a class="ce-btn ce-btn-{esc(variant)}" href="{esc(url)}" '
                f'style="{style}"{track}>{esc(p.get("text") or "")}</a>')

    def r_landing_button_group(self, node: dict) -> str:
        p = node.get("props") or {}
        gap = int(p.get("gap") or 12)
        style = style_str({"display": "flex", "gap": f"{gap}px", "flex-wrap": "wrap",
                           "justify-content": {"left": "flex-start", "center": "center",
                                              "right": "flex-end",
                                              "space-between": "space-between"}.get(
                               p.get("align", "center"), "center"),
                           "margin-bottom": "16px"})
        return f'<div class="ce-btn-group" style="{style}">{self._children_html(node)}</div>'

    def r_landing_countdown(self, node: dict) -> str:
        p = node.get("props") or {}
        target = esc(p.get("target") or "")
        parts = "".join(
            f'<div class="ce-cd-cell"><span class="ce-cd-num" data-ce-cd="{k}">--</span>'
            f'<span class="ce-cd-label">{lbl}</span></div>'
            for k, lbl in (("d", "天"), ("h", "时"), ("m", "分"), ("s", "秒")))
        return (f'<div class="ce-countdown" data-ce-countdown="{target}" '
                f'data-expired="{esc(p.get("expired_text") or "")}">'
                f'<div class="ce-cd-title">{esc(p.get("title") or "")}</div>'
                f'<div class="ce-cd-row">{parts}</div></div>')

    def r_landing_feature_grid(self, node: dict) -> str:
        p = node.get("props") or {}
        cols = int(p.get("columns") or 3)
        items = "".join(
            f'<div class="ce-feature"><div class="ce-feature-icon">'
            f'{esc(it.get("icon") or "")}</div>'
            f'<h3 class="ce-feature-title">{esc(it.get("title") or "")}</h3>'
            f'<p class="ce-feature-desc">{esc(it.get("desc") or "")}</p></div>'
            for it in (p.get("items") or []) if isinstance(it, dict))
        style = style_str({"display": "grid", "gap": "24px",
                           "grid-template-columns": f"repeat(auto-fit,minmax({220 // max(1, cols)}px,1fr))"})
        return f'<div class="ce-features" style="{style}">{items}</div>'

    def r_landing_stat_row(self, node: dict) -> str:
        p = node.get("props") or {}
        items = "".join(
            f'<div class="ce-stat"><div class="ce-stat-value">{esc(it.get("value"))}</div>'
            f'<div class="ce-stat-label">{esc(it.get("label"))}</div></div>'
            for it in (p.get("items") or []) if isinstance(it, dict))
        return (f'<div class="ce-stats" style="display:grid;gap:16px;'
                f'grid-template-columns:repeat(auto-fit,minmax(140px,1fr))">{items}</div>')

    def r_landing_social_proof(self, node: dict) -> str:
        p = node.get("props") or {}
        stars = "★" * int(round(float(p.get("rating") or 5)))
        style = style_str({"display": "flex", "gap": "12px", "align-items": "center",
                           "flex-wrap": "wrap"})
        return (f'<div class="ce-proof" style="{style}">'
                f'<span style="color:{_t(self.t,"accent")};font-size:20px">{stars}</span>'
                f'<strong>{esc(p.get("rating"))}</strong>'
                f'<span style="color:{_t(self.t,"text_muted")}">'
                f'{esc(p.get("count") or "")} 条评价 · {esc(p.get("source") or "")}</span>'
                f'{f"<q>{esc(p["quote"])}</q>" if p.get("quote") else ""}</div>')

    def r_landing_ticket_cards(self, node: dict) -> str:
        p = node.get("props") or {}
        cards = []
        for c in (p.get("cards") or []):
            if not isinstance(c, dict):
                continue
            sold = bool(c.get("sold_out"))
            price = ('<span class="ce-tk-price ce-tk-sold">已售罄</span>' if sold else
                     f'<span class="ce-tk-price">{esc(c.get("price"))}</span>'
                     + (f'<span class="ce-tk-old">{esc(c.get("old_price"))}</span>'
                        if c.get("old_price") else ""))
            tag = (f'<span class="ce-tk-tag">{esc(c.get("tag"))}</span>' if c.get("tag") else "")
            img = (f'<img src="{esc(_clean_url(c["image"]))}" alt="{esc(c.get("name"))}" '
                   'style="width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px 8px 0 0">'
                   if c.get("image") else "")
            if sold:
                cta = ('<button class="ce-btn ce-btn-ghost" disabled '
                       'style="border:2px solid #e5e7eb;color:#9ca3af;padding:12px 28px;'
                       'border-radius:999px;width:100%;opacity:.6">售罄</button>')
            else:
                cta = (f'<a class="ce-btn ce-btn-primary" '
                       f'href="{esc(with_utm(_clean_url(c.get("url")), ""))}" data-track="ticket" '
                       f'style="background:{_t(self.t,"brand")};color:#fff;padding:12px 28px;'
                       f'border-radius:999px;text-align:center">立即购票</a>')
            cards.append(
                f'<div class="ce-tk{" is-sold" if sold else ""}">{img}'
                f'<div class="ce-tk-body">{tag}'
                f'<h3 class="ce-tk-name">{esc(c.get("name"))}</h3>'
                f'<p class="ce-tk-desc">{esc(c.get("desc"))}</p>'
                f'<div class="ce-tk-row">{price}</div>{cta}</div></div>')
        layout = p.get("layout", "grid")
        if layout == "list":
            style = style_str({"display": "flex", "flex-direction": "column", "gap": "16px"})
        else:
            style = style_str({"display": "grid", "gap": "20px",
                               "grid-template-columns": "repeat(auto-fit,minmax(240px,1fr))"})
        return f'<div class="ce-tickets" style="{style}">{"".join(cards)}</div>'

    def r_landing_faq(self, node: dict) -> str:
        p = node.get("props") or {}
        items = []
        for i, it in enumerate((p.get("items") or [])):
            if not isinstance(it, dict):
                continue
            open_first = i == 0 and p.get("default_open_first", True)
            items.append(
                f'<details class="ce-faq-item"{" open" if open_first else ""}>'
                f'<summary>{esc(it.get("q"))}</summary>'
                f'<div class="ce-faq-a">{esc(it.get("a"))}</div></details>')
        return f'<div class="ce-faq">{"".join(items)}</div>'

    def r_landing_map(self, node: dict) -> str:
        p = node.get("props") or {}
        head = (f'<h3 class="ce-h">{esc(p.get("title"))}</h3>' if p.get("title") else "")
        info = ""
        if p.get("address") or p.get("note"):
            info = (f'<p class="ce-p">{esc(p.get("address"))}</p>'
                    f'<p class="ce-p ce-muted">{esc(p.get("note"))}</p>')
        if p.get("map_embed"):
            embed = (f'<div class="ce-map" style="border-radius:{_t(self.t,"radius")};'
                     f'overflow:hidden;height:320px">'
                     f'<iframe src="{esc(_clean_url(p["map_embed"]))}" style="width:100%;'
                     f'height:100%;border:0" loading="lazy" title="{esc(p.get("title"))}" '
                     f'referrerpolicy="no-referrer-when-downgrade"></iframe></div>')
            return f'<div class="ce-mapwrap">{head}{embed}{info}</div>'
        return f'<div class="ce-mapwrap">{head}{info}</div>'

    def r_landing_form_embed(self, node: dict) -> str:
        p = node.get("props") or {}
        fid = esc(p.get("form_id") or "")
        mode = p.get("embed_mode", "inline")
        head = (f'<h3 class="ce-h">{esc(p.get("title"))}</h3>' if p.get("title") else "")
        if mode == "inline":
            # 服务端把关联表单渲染进来（content_id 存在 meta）
            body = (f'<div class="ce-formslot" data-ce-form-slot="{fid}">'
                    f'<!-- 由 /api/contents/{fid}/form-html 填充 -->'
                    f'</div>')
            return f'<div class="ce-formembed">{head}{body}</div>'
        cta = p.get("cta_text") or "立即报名"
        return (f'<div class="ce-formembed ce-formembed-{esc(mode)}">'
                f'<button class="ce-btn ce-btn-primary" data-ce-open-form="{fid}" '
                f'style="background:{_t(self.t,"brand")};color:#fff;padding:14px 32px;'
                f'border-radius:999px">{esc(cta)}</button></div>')

    def r_landing_spacer(self, node: dict) -> str:
        h = int((node.get("props") or {}).get("height") or 48)
        return f'<div style="height:{h}px" aria-hidden="true"></div>'

    def r_landing_social_links(self, node: dict) -> str:
        p = node.get("props") or {}
        links = "".join(
            f'<a href="{esc(_clean_url(i.get("url")))}" target="_blank" rel="noopener" '
            f'style="color:inherit;text-decoration:underline;margin-right:12px">'
            f'{esc(i.get("name"))}</a>'
            for i in (p.get("items") or []) if isinstance(i, dict))
        return f'<div class="ce-social">{links}</div>'

    def r_landing_footer(self, node: dict) -> str:
        p = node.get("props") or {}
        st = node.get("style") or {}
        bg = st.get("background_color") or p.get("bg_color") or _t(self.t, "secondary")
        color = p.get("color") or "#c9d1d9"
        cols = int(p.get("columns") or 4)
        extra = self._children_html(node)
        legal_links = []
        if p.get("privacy_url"):
            legal_links.append(f'<a href="{esc(_clean_url(p["privacy_url"]))}" '
                               f'style="color:inherit">隐私政策</a>')
        if p.get("terms_url"):
            legal_links.append(f'<a href="{esc(_clean_url(p["terms_url"]))}" '
                               f'style="color:inherit">服务条款</a>')
        legal = (" · ".join(legal_links) +
                 (f" · {esc(p['legal'])}" if p.get("legal") else ""))
        style = style_str({"background-color": bg, "color": color,
                           "padding": st.get("padding") or "48px 20px", "text-align": "center"})
        return (f'<footer class="ce-footer" style="{style}">'
                f'<div class="ce-container">'
                f'<div class="ce-footer-grid" style="display:grid;gap:24px;'
                f'grid-template-columns:repeat(auto-fit,minmax(180px,1fr))">{extra}</div>'
                f'{f"<p style=margin-top:24px;font-size:13px;opacity:.85>{esc(legal)}</p>" if legal else ""}'
                f'</div></footer>')

    # -------------------------------------------------- CSS
    def _css(self, width: str, font: str, bg: str) -> str:
        return _clean_css(f"""
*{{box-sizing:border-box}}
body{{margin:0;padding:0;background:{bg};color:{_t(self.t,'text')};
font-family:{font};line-height:{_t(self.t,'line_height')};
-webkit-font-smoothing:antialiased}}
.ce-container{{width:100%;max-width:{width};margin:0 auto;padding:0 20px}}
.ce-nav{{position:relative;z-index:50;border-bottom:1px solid {_t(self.t,'border')}}}
.ce-sticky{{position:sticky;top:0}}
.ce-nav-inner{{display:flex;align-items:center;justify-content:space-between;gap:16px}}
.ce-logo{{font-weight:800;font-size:20px;color:{_t(self.t,'secondary')}}}
.ce-nav-links{{display:flex;gap:20px;flex-wrap:wrap}}
.ce-nav-link{{color:{_t(self.t,'text_muted')};text-decoration:none;font-size:15px}}
.ce-nav-link:hover{{color:{_t(self.t,'brand')}}}
.ce-hero-overlay{{pointer-events:none}}
.ce-hero-centered .ce-hero-inner{{text-align:center}}
.ce-hero-centered .ce-hero-inner .ce-btn-group{{justify-content:center}}
.ce-h{{font-family:inherit}}
.ce-btn{{display:inline-block;text-decoration:none;font-weight:600;transition:opacity .15s}}
.ce-btn:hover{{opacity:.88}}
.ce-countdown{{text-align:center;margin:24px 0}}
.ce-cd-title{{font-size:14px;opacity:.85;margin-bottom:12px;color:inherit}}
.ce-cd-row{{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}}
.ce-cd-cell{{background:rgba(255,255,255,.12);border-radius:8px;padding:10px 14px;
min-width:64px;color:inherit}}
.ce-cd-num{{display:block;font-size:26px;font-weight:800}}
.ce-cd-label{{display:block;font-size:12px;opacity:.8}}
.ce-feature{{background:{_t(self.t,'bg_subtle')};border-radius:{_t(self.t,'radius')};
padding:24px;text-align:left}}
.ce-feature-icon{{font-size:28px;margin-bottom:8px}}
.ce-feature-title{{margin:0 0 8px;font-size:18px;color:{_t(self.t,'secondary')}}}
.ce-feature-desc{{margin:0;color:{_t(self.t,'text_muted')};font-size:15px}}
.ce-stat{{text-align:center}}
.ce-stat-value{{font-size:32px;font-weight:800;color:{_t(self.t,'brand')}}}
.ce-stat-label{{font-size:14px;color:{_t(self.t,'text_muted')}}}
.ce-tk{{border:1px solid {_t(self.t,'border')};border-radius:{_t(self.t,'radius')};
overflow:hidden;background:#fff;display:flex;flex-direction:column}}
.ce-tk.is-sold{{opacity:.72}}
.ce-tk-body{{padding:18px;display:flex;flex-direction:column;gap:8px;flex:1}}
.ce-tk-tag{{background:{_t(self.t,'brand_light')};color:{_t(self.t,'brand_dark')};
font-size:12px;padding:2px 8px;border-radius:999px;align-self:flex-start}}
.ce-tk-name{{margin:0;font-size:18px}}
.ce-tk-desc{{margin:0;font-size:14px;color:{_t(self.t,'text_muted')};flex:1}}
.ce-tk-row{{display:flex;align-items:baseline;gap:8px}}
.ce-tk-price{{font-size:22px;font-weight:800;color:{_t(self.t,'brand')}}}
.ce-tk-price.ce-tk-sold{{color:{_t(self.t,'text_muted')}}}
.ce-tk-old{{text-decoration:line-through;color:{_t(self.t,'text_muted')};font-size:14px}}
.ce-faq-item{{border-bottom:1px solid {_t(self.t,'border')};padding:14px 0}}
.ce-faq-item summary{{cursor:pointer;font-weight:600;color:{_t(self.t,'secondary')}}}
.ce-faq-a{{color:{_t(self.t,'text_muted')};padding:10px 0 2px;font-size:15px}}
.ce-proof q{{color:{_t(self.t,'text_muted')}}}
.ce-muted{{color:{_t(self.t,'text_muted')}}}
.ce-video iframe,.ce-map iframe{{display:block}}
@media (max-width:768px){{
  .ce-nav-links{{display:none}}
  .ce-hero-split{{text-align:left}}
  .ce-cd-cell{{min-width:56px;padding:8px 10px}}
  .ce-cd-num{{font-size:22px}}
}}
@media print{{
  .ce-nav,.ce-btn-group{{display:none}}
  .ce-section{{padding:12px 0 !important}}
}}
""")

    # -------------------------------------------------- JS（仅增强）
    def _js(self) -> str:
        return r"""(function(){
'use strict';
// 倒计时
document.querySelectorAll('[data-ce-countdown]').forEach(function(el){
  var target = new Date(el.getAttribute('data-ce-countdown')).getTime();
  var expired = el.getAttribute('data-expired')||'';
  if (isNaN(target)) return;
  function tick(){
    var diff = target - Date.now();
    if (diff <= 0){
      el.innerHTML = '<div class="ce-cd-title">'+expired+'</div>';
      return;
    }
    var s = Math.floor(diff/1000);
    var d = Math.floor(s/86400), h = Math.floor(s%86400/3600),
        m = Math.floor(s%3600/60), sec = s%60;
    var map = {d:d,h:h,m:m,s:sec};
    el.querySelectorAll('[data-ce-cd]').forEach(function(n){
      n.textContent = String(map[n.getAttribute('data-ce-cd')]).padStart(2,'0');
    });
  }
  tick(); setInterval(tick, 1000);
});
// 弹层/抽屉表单
document.addEventListener('click', function(e){
  var t = e.target.closest('[data-ce-open-form]');
  if (!t) return;
  var id = t.getAttribute('data-ce-open-form');
  var slot = document.querySelector('[data-ce-form-slot="'+id+'"]');
  if (!slot) return;
  var html = slot.innerHTML.trim();
  if (!html) return;
  var box = document.createElement('div');
  box.className = 'ce-modal';
  box.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:9999;'
    + 'display:flex;align-items:center;justify-content:center;padding:20px';
  var inner = document.createElement('div');
  inner.style.cssText = 'background:#fff;border-radius:8px;max-width:560px;width:100%;'
    + 'max-height:86vh;overflow:auto;padding:24px';
  inner.innerHTML = html;
  box.appendChild(inner);
  box.addEventListener('click', function(ev){ if (ev.target === box) box.remove(); });
  document.body.appendChild(box);
  document.body.style.overflow = 'hidden';
  var f = inner.querySelector('form');
  if (f) setTimeout(function(){ f.scrollIntoView({behavior:'smooth'}); }, 50);
});
document.addEventListener('keydown', function(e){
  if (e.key === 'Escape'){ var m = document.querySelector('.ce-modal');
    if (m) { m.remove(); document.body.style.overflow=''; } }
});
// CTA 埋点（可替换为 GA4 / Mautic tracking）
document.addEventListener('click', function(e){
  var t = e.target.closest('[data-track]');
  if (!t) return;
  if (window.dataLayer) window.dataLayer.push({
    event:'ce_cta_click', track:t.getAttribute('data-track'), href:t.getAttribute('href')
  });
});
})();"""


_SCRIPT_RE = re.compile(r"<\s*script\b.*?<\s*/\s*script\s*>", re.I | re.S)
_EVENT_RE = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)


def _sanitize_html(raw: str) -> str:
    if not raw:
        return ""
    s = _SCRIPT_RE.sub("", str(raw))
    s = _EVENT_RE.sub("", s)
    s = re.sub(r"<\s*(iframe|object|embed)\b[^>]*>.*?<\s*/\s*\1\s*>", "", s, flags=re.I | re.S)
    s = re.sub(r"\son(?:load|error|click|mouseover)\s*=\s*\"[^\"]*\"", "", s, flags=re.I)
    s = re.sub(r"javascript\s*:", "", s, flags=re.I)
    return s.strip()


def render_landing(schema: dict, tokens: dict | None = None, **kw) -> str:
    return LandingRenderer(tokens).render(schema, **kw)