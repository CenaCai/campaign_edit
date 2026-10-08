"""HTML 邮件渲染器。

产出目标：Outlook 2016 / Gmail / Apple Mail / QQ 邮箱 / Outlook.com 全部正常显示。
硬约束（代码层面强制，不依赖编辑器自觉）：
* table 布局，禁止 flex/grid/position；
* 所有视觉属性写成 inline style（邮件客户端普遍剥离 <style>）；
* 移动端靠 media query + 单一 max-width 容器；
* <style> 里只放响应式与暗色模式补丁；
* VML 兜底 Outlook 按钮圆角；
* 所有图片带 alt；所有链接带 title 与安全协议校验。
"""
from __future__ import annotations

import re
from typing import Any

from .common import block_style, esc, plain_text, split_box_shadow, style_str, with_utm
from .theme import merge_tokens

_RANK_ORDER = ["hero", "layout", "text", "media", "action", "commerce", "social", "basic"]


def _t(tokens: dict, key: str) -> str:
    return str(tokens.get(key, ""))


def _sanitize_url(url: str, *, allow_anchor: bool = True) -> str:
    u = (url or "").strip()
    if not u:
        return "#"
    if u.startswith(("javascript:", "data:", "vbscript:")):
        return "#"
    if u.startswith("#"):
        return u if allow_anchor else "#"
    if u.startswith("mailto:") or u.startswith("tel:"):
        return u
    if u.startswith("//"):
        return "https:" + u
    if not re.match(r"^https?://", u, flags=re.I):
        return "https://" + u.lstrip("/")
    return u


def _vml_button(text: str, url: str, bg: str, fg: str, size: str) -> str:
    """Outlook (Word 渲染引擎) 圆角按钮兜底。"""
    sizes = {"sm": ("padding:6px 14px;font-size:13px", 26),
             "md": ("padding:11px 26px;font-size:15px", 40),
             "lg": ("padding:14px 34px;font-size:17px", 46)}
    style, _h = sizes.get(size, sizes["md"])
    vml = (
        '<!--[if mso]><v:roundrect xmlns:v="urn:schemas-microsoft-com:vml" '
        f'arcsize="24%" stroke="f" fillcolor="{bg}"><w:anchorlock/>'
        f'<center style="color:{fg};{style};font-family:Arial,sans-serif;font-weight:bold;">'
        f"{esc(text)}</center>"
        f'</v:roundrect><![endif]-->'
    )
    anchor = (
        f'<a href="{esc(_sanitize_url(url))}" style="{style};background:{bg};color:{fg};'
        'text-decoration:none;border-radius:6px;display:inline-block;font-family:Arial,'
        'sans-serif;font-weight:bold;mso-hide:all;">'
        f"{esc(text)}</a>"
    )
    return vml + anchor


class EmailRenderer:
    kind = "email"

    def __init__(self, tokens: dict[str, str] | None = None) -> None:
        self.t = merge_tokens(tokens)

    # -------------------------------------------------- 主入口
    def render(self, schema: dict, *, inline_css: bool = True,
               with_dark_mode: bool = True, with_responsive: bool = True) -> str:
        root = schema.get("root") or {}
        doc = schema.get("doc") or {}
        width = root.get("props", {}).get("width") or _t(self.t, "email_width")
        bg = root.get("props", {}).get("bg_color") or _t(self.t, "bg_subtle")
        align = root.get("props", {}).get("align") or "center"

        head = self._head(schema, doc, with_dark_mode, with_responsive, width)
        body_rows = "".join(self._node(n) for n in (root.get("children") or [])
                            if not n.get("hidden"))
        # 排序：让 hero 顶部、footer 底部（编辑器乱序也能得到合理结果）
        inner_style = style_str({
            "max-width": width, "background-color": _t(self.t, "bg"),
            "margin": "0 auto", "font-family": _t(self.t, "font_family"),
            "border-radius": _t(self.t, "radius"), "overflow": "hidden",
        })
        inner = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                 f'border="0" style="width:100%;background-color:{esc(bg)};padding:24px 8px;">'
                 f'<tr><td align="{esc(align)}" valign="top">'
                 f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                 f'style="{inner_style}" width="{esc(width)}">'
                 f'{body_rows}</table></td></tr></table>')

        preheader = self._preheader(doc.get("preheader") or doc.get("subject") or "")
        return f"<!DOCTYPE html>{head}<body>{preheader}{inner}</body></html>"

    # -------------------------------------------------- head / preheader
    def _head(self, schema: dict, doc: dict, dark: bool, responsive: bool,
              width: str) -> str:
        subject = esc(doc.get("subject") or "(无主题)")
        css: list[str] = []

        if responsive:
            px = re.sub(r"[^0-9]", "", width) or "600"
            mobile_rules = [
                f".ce-container{{width:100% !important;max-width:{px}px !important}}",
                ".ce-pad{padding-left:16px !important;padding-right:16px !important}",
                ".ce-h1{font-size:24px !important;line-height:1.3 !important}",
                ".ce-btn{display:block !important;width:auto !important}",
                ".ce-hide-mobile{display:none !important}",
                ".ce-stack{display:block !important;width:100% !important}",
            ]
            css.append("@media only screen and (max-width:640px){" + "".join(mobile_rules) + "}")

        if dark:
            dark_rules = [
                ".ce-dark-bg{background-color:#111827 !important}",
                ".ce-dark-text{color:#f3f4f6 !important}",
            ]
            css.append("@media (prefers-color-scheme:dark){" + "".join(dark_rules) + "}")

        base_rules = [
            "body{margin:0;padding:0;background-color:" + _t(self.t, "bg_subtle") + "}",
            "img{border:0;outline:none;text-decoration:none}",
            "table{border-collapse:collapse !important}",
        ]
        css.append("".join(base_rules))

        return (
            '<html lang="zh-CN" xmlns:v="urn:schemas-microsoft-com:vml" '
            'xmlns:o="urn:schemas-microsoft-com:office:office">'
            '<head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<meta name="color-scheme" content="light dark">'
            '<meta name="supported-color-schemes" content="light dark">'
            f"<title>{subject}</title>"
            '<!--[if mso]><noscript><xml><o:OfficeDocumentSettings>'
            '<o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml>'
            "</noscript><![endif]-->"
            f"<style>{''.join(css)}</style></head>"
        )

    def _preheader(self, text: str) -> str:
        filler = "" * 60
        return (
            '<div style="display:none;font-size:1px;line-height:1px;max-height:0;'
            'max-width:0;opacity:0;overflow:hidden;mso-hide:all">'
            f"{esc(text)}{filler}</div>"
        )

    # -------------------------------------------------- 分发
    def _node(self, node: dict) -> str:
        fn = getattr(self, f"r_{node.get('type', '').replace('.', '_')}", None)
        if fn is None:
            return ""
        return fn(node)

    # -------------------------------------------------- root / 容器
    def r_email_root(self, node: dict) -> str:  # root 本身不产出内容
        return ""

    def _cell(self, inner: str, *, width: str = "100%", bg: str = "",
              pad: str = "", valign: str = "top") -> str:
        style = style_str({"width": width, "background-color": bg, "padding": pad,
                           "vertical-align": valign, "text-align": "left"})
        return (f'<td class="ce-pad" style="{style}" valign="{esc(valign)}">{inner}</td>')

    def _table(self, inner: str, *, width: str = "100%") -> str:
        return (f'<table role="presentation" width="{esc(width)}" cellpadding="0" '
                f'cellspacing="0" border="0" style="width:{esc(width)};'
                f'max-width:{esc(width)}">{inner}</table>')

    # -------------------------------------------------- 组件
    def r_email_header(self, node: dict) -> str:
        p = node.get("props", {})
        bg = p.get("bg_color") or ""
        align = p.get("align", "left")
        pad = (node.get("style") or {}).get("padding") or "24px 32px"
        logo = ""
        if p.get("logo_url"):
            h = int(p.get("logo_height") or 40)
            logo = (f'<img src="{esc(_sanitize_url(p["logo_url"]))}" '
                    f'alt="{esc(p.get("alt") or "Logo")}" height="{h}" '
                    f'style="height:{h}px;width:auto;border:0;display:inline-block">')
        else:
            logo = plain_text("".join(self._node(c) for c in node.get("children") or [])) or p.get("alt", "")
            logo = (f'<span style="font-size:20px;font-weight:700;color:'
                    f'{_t(self.t, "secondary")}">{esc(logo)}</span>')
        return (f'<tr><td align="{esc(align)}" style="padding:{pad};'
                f'background-color:{esc(bg)}">{logo}</td></tr>')

    def r_email_hero(self, node: dict) -> str:
        p = node.get("props", {})
        st = node.get("style") or {}
        bg = st.get("background_color") or p.get("bg_color") or _t(self.t, "secondary")
        pt = int(p.get("pad_top") or 40)
        pb = int(p.get("pad_bottom") or 40)
        pad = st.get("padding") or f"{pt}px 32px"
        bg_img = ""
        if p.get("bg_image"):
            bg_img = (f'background-image:url({esc(_sanitize_url(p["bg_image"]))});'
                      'background-size:cover;background-position:center;')
        inner = "".join(self._node(c) for c in node.get("children") or [])
        return (f'<tr><td style="padding:{pad};background-color:{esc(bg)};{bg_img}">'
                f'{inner or self._placeholder("请在首屏添加标题/按钮")}</td></tr>')

    def r_email_text(self, node: dict) -> str:
        p = node.get("props", {})
        st = node.get("style") or {}
        fs = p.get("font_size") or st.get("font_size") or _t(self.t, "font_size_base")
        color = p.get("color") or st.get("color") or _t(self.t, "text")
        lh = p.get("line_height") or _t(self.t, "line_height")
        align = p.get("align", "left")
        pad = st.get("padding") or p.get("pad") or "16px 32px"
        html = p.get("html") or ""
        children = "".join(self._node(c) for c in node.get("children") or [])
        inner = (children or _sanitize_inline_html(html))
        wrap = (f'<div style="font-size:{esc(fs)};color:{esc(color)};line-height:{lh};'
                f'text-align:{esc(align)}">{inner}</div>')
        if children:
            return f"<tr><td style=\"padding:{pad}\">{wrap}</td></tr>"
        return f'<tr><td style="padding:{pad};text-align:{esc(align)}">{inner}</td></tr>'

    def r_email_heading(self, node: dict) -> str:
        p = node.get("props", {})
        lvl = p.get("level", "h2")
        sizes = {"h1": "30px", "h2": "24px", "h3": "19px"}
        st = node.get("style") or {}
        style = style_str({
            "font-size": st.get("font_size") or sizes.get(lvl, "24px"),
            "color": st.get("color") or p.get("color") or _t(self.t, "secondary"),
            "text-align": st.get("text_align") or p.get("align", "left"),
            "line-height": "1.3", "margin": "0 0 12px", "font-weight": "700",
        })
        cls = ' class="ce-h1"' if lvl == "h1" else ""
        return (f'<tr><td style="padding:16px 32px 8px"><{lvl}{cls} style="{style}">'
                f'{esc(p.get("text") or "")}</{lvl}></td></tr>')

    def r_email_image(self, node: dict) -> str:
        p = node.get("props", {})
        src = _sanitize_url(p.get("src") or "")
        alt = p.get("alt") or ""
        if not alt:
            alt = "image"
        w = p.get("width") or "100%"
        style = style_str({"width": w, "max-width": "100%", "border-radius": p.get("radius", "0"),
                           "display": "block", "border": "0"})
        img = (f'<img src="{esc(src)}" alt="{esc(alt)}" width="{esc(w)}" style="{style}">')
        if p.get("href"):
            img = (f'<a href="{esc(_sanitize_url(p["href"]))}" target="_blank" '
                   f'style="text-decoration:none">{img}</a>')
        return f'<tr><td style="padding:8px 32px">{img}</td></tr>'

    def r_email_button(self, node: dict) -> str:
        p = node.get("props", {})
        url = with_utm(_sanitize_url(p.get("url") or ""), p.get("utm_params") or "")
        bg = p.get("bg_color") or _t(self.t, "brand")
        fg = p.get("text_color") or _t(self.t, "text_inverse")
        size = p.get("size", "md")
        _shadow, radius = split_box_shadow(_t(self.t, "radius"))
        radius = p.get("radius") or radius
        btn = _vml_button(p.get("text") or "按钮", url, bg, fg, size)
        if p.get("full_width"):
            return (f'<tr><td align="center" style="padding:16px 32px">'
                    f'<div style="width:100%">{btn}</div></td></tr>')
        return (f'<tr><td align="center" class="ce-btn" style="padding:16px 32px">'
                f'{btn}</td></tr>')

    def r_email_button_group(self, node: dict) -> str:
        align = (node.get("props") or {}).get("align", "center")
        kids = node.get("children") or []
        if len(kids) == 1:
            return self._node(kids[0])
        inner = "".join(self.r_email_button(k) for k in kids)
        return (f'<tr><td align="{esc(align)}" style="padding:8px 32px">'
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin:0 auto"><tr>{inner}</tr></table></td></tr>')

    def r_email_columns(self, node: dict) -> str:
        p = node.get("props") or {}
        gap = int(p.get("gap") or 16)
        kids = node.get("children") or []
        if not kids:
            return ""
        bg = p.get("bg_color") or ""
        cells = ""
        for k in kids:
            span = int((k.get("props") or {}).get("span") or 1)
            w = f"{100 // max(1, span)}%"
            inner = "".join(self._node(c) for c in k.get("children") or []) or self._placeholder("空列")
            cells += (f'<td class="ce-stack" width="{esc(w)}" valign="top" '
                      f'style="width:{esc(w)};padding:{gap // 2}px;'
                      f'font-size:0;text-align:left">{inner}</td>')
        spacer = (f'<td class="ce-hide-mobile" width="{gap}" '
                  f'style="width:{gap}px;font-size:0">&nbsp;</td>') if len(kids) > 1 else ""
        half = f'<td class="ce-hide-mobile" style="font-size:0">&nbsp;</td>' if len(kids) > 1 else ""
        return (f'<tr><td style="padding:8px 24px;background-color:{esc(bg)}">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'border="0" style="width:100%"><tr>{cells}{spacer}</tr></table>{half}</td></tr>')

    def r_email_column(self, node: dict) -> str:
        return "".join(self._node(c) for c in node.get("children") or [])

    def r_email_divider(self, node: dict) -> str:
        p = node.get("props", {})
        return (f'<tr><td style="padding:12px 32px">'
                f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
                f'border="0" style="width:100%"><tr><td style="height:1px;line-height:1px;'
                f'background-color:{esc(p.get("color") or _t(self.t, "border"))};'
                f'font-size:0">&nbsp;</td></tr></table></td></tr>')

    def r_email_spacer(self, node: dict) -> str:
        h = int((node.get("props") or {}).get("height") or 24)
        return f'<tr><td style="height:{h}px;font-size:0;line-height:{h}px">&nbsp;</td></tr>'

    def r_email_product_card(self, node: dict) -> str:
        p = node.get("props", {})
        align = p.get("align", "left")
        img = ""
        if p.get("image"):
            img = (f'<img src="{esc(_sanitize_url(p["image"]))}" alt="{esc(p.get("title"))}" '
                   'style="width:100%;max-width:100%;border-radius:6px;display:block;'
                   'margin:0 0 12px">')
        price_row = f'<span style="font-size:20px;font-weight:700;color:{_t(self.t, "brand")}">' \
                    f'{esc(p.get("price"))}</span>'
        if p.get("old_price"):
            price_row += (f' <span style="font-size:14px;color:{_t(self.t, "text_muted")};'
                          f'text-decoration:line-through">{esc(p["old_price"])}</span>')
        badge = ""
        if p.get("badge"):
            badge = (f'<span style="display:inline-block;background:{_t(self.t, "brand_light")};'
                     f'color:{_t(self.t, "brand_dark")};font-size:12px;padding:2px 8px;'
                     f'border-radius:999px;margin-bottom:8px">{esc(p["badge"])}</span>')
        cta = ""
        if p.get("url"):
            cta = (f'<a href="{esc(_sanitize_url(p["url"]))}" style="display:inline-block;'
                   f'margin-top:12px;background:{_t(self.t, "brand")};color:#fff;padding:10px 20px;'
                   f'border-radius:6px;text-decoration:none;font-weight:bold">查看详情</a>')
        style = style_str({
            "border": f"1px solid {_t(self.t, 'border')}",
            "border-radius": _t(self.t, "radius"), "padding": "16px",
            "background-color": _t(self.t, "bg"), "text-align": align,
        })
        return (f'<tr><td style="padding:12px 16px"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0" style="{style}">'
                f'<tr><td>{img}{badge}'
                f'<div style="font-size:17px;font-weight:700;color:{_t(self.t, "text")}">'
                f'{esc(p.get("title"))}</div>'
                f'<div style="font-size:14px;color:{_t(self.t, "text_muted")};margin:4px 0 10px">'
                f'{esc(p.get("desc"))}</div>'
                f'<div>{price_row}</div>{cta}</td></tr></table></td></tr>')

    def r_email_ticket_card(self, node: dict) -> str:
        p = node.get("props", {})
        sold = p.get("sold_out")
        price = "已售罄" if sold else f"£{esc(p.get('price_from') or '0')}"
        price_color = _t(self.t, "text_muted") if sold else _t(self.t, "brand")
        url = _sanitize_url(p.get("url") or "#")
        cta_text = "售罄" if sold else "立即购票"
        bg = _t(self.t, "bg_subtle") if sold else _t(self.t, "brand")
        return (f'<tr><td style="padding:12px 24px"><table role="presentation" width="100%" '
                f'cellpadding="0" cellspacing="0" border="0" style="background:'
                f'{_t(self.t, "bg")};border:2px solid {_t(self.t, "secondary")};border-radius:8px">'
                f'<tr><td style="padding:20px">'
                f'<div style="font-size:18px;font-weight:700;color:{_t(self.t, "secondary")}">'
                f'{esc(p.get("event_name"))}</div>'
                f'<div style="font-size:14px;color:{_t(self.t, "text_muted")};margin:6px 0">'
                f'🗓 {esc(p.get("date"))} &nbsp;·&nbsp; 📍 {esc(p.get("venue"))}</div>'
                f'<div style="font-size:24px;font-weight:700;color:{price_color};margin:10px 0">'
                f'{price}</div>'
                f'<a href="{esc(url)}" style="display:inline-block;background:{bg};color:#fff;'
                f'padding:10px 24px;border-radius:6px;text-decoration:none;font-weight:bold">'
                f'{esc(cta_text)}</a></td></tr></table></td></tr>')

    def r_email_countdown(self, node: dict) -> str:
        p = node.get("props", {})
        target = esc(p.get("target") or "")
        bg = p.get("bg_color") or _t(self.t, "secondary")
        color = p.get("color") or "#ffffff"
        # 邮件不能跑 JS：用服务端渲染好的静态值 + Outlook 条件注释兜底文案
        return (f'<tr><td style="padding:20px 32px;background:{esc(bg)};text-align:center">'
                f'<div style="color:{esc(color)};font-size:14px;opacity:.85">'
                f'{esc(p.get("title"))}</div>'
                f'<div style="color:{esc(color)};font-size:34px;font-weight:700;letter-spacing:2px">'
                f'--<span>天</span> --<span>时</span> --<span>分</span></div>'
                f'<div style="display:none;max-height:0;overflow:hidden">{target}</div>'
                f'</td></tr>')

    def r_email_social(self, node: dict) -> str:
        icons = (node.get("props") or {}).get("icons") or []
        color = (node.get("props") or {}).get("color") or _t(self.t, "text_muted")
        links = "".join(
            f'<a href="{esc(_sanitize_url(i.get("url")))}" target="_blank" '
            f'style="display:inline-block;margin:0 10px;color:{esc(color)};font-size:13px;'
            f'text-decoration:none">{esc(i.get("name"))}</a>'
            for i in icons if isinstance(i, dict)
        )
        return f'<tr><td align="center" style="padding:20px 32px">{links}</td></tr>'

    def r_email_footer(self, node: dict) -> str:
        p = node.get("props", {})
        bg = p.get("bg_color") or _t(self.t, "secondary")
        color = p.get("color") or "#c9d1d9"
        children = "".join(self._node(c) for c in node.get("children") or [])
        base_style = style_str({
            "font-size": "12px", "line-height": "1.7", "color": esc(color),
            "text-align": "center", "padding": "24px 32px",
        })
        parts = [f'<div style="{base_style}">']
        if children:
            parts.append(children)
        if p.get("company"):
            parts.append(f'<div style="margin-top:8px;font-weight:700">{esc(p["company"])}</div>')
        if p.get("address"):
            parts.append(f'<div style="opacity:.8">{esc(p["address"])}</div>')
        links = []
        if p.get("preferences_url"):
            links.append(f'<a href="{esc(_sanitize_url(p["preferences_url"]))}" '
                         f'style="color:{esc(color)};text-decoration:underline">偏好设置</a>')
        if p.get("unsubscribe_url"):
            text = p.get("unsubscribe_text") or "退订"
            links.append(f'<a href="{esc(_sanitize_url(p["unsubscribe_url"]))}" '
                         f'style="color:{esc(color)};text-decoration:underline">{esc(text)}</a>')
        if links:
            parts.append(f'<div style="margin-top:12px">{" · ".join(links)}</div>')
        parts.append("</div>")
        return f'<tr><td style="background:{esc(bg)}">{"".join(parts)}</td></tr>'

    def r_email_section(self, node: dict) -> str:
        # 插件可注册；内置未提供，退化为容器
        return "".join(self._node(c) for c in node.get("children") or [])

    # -------------------------------------------------- 工具
    def _placeholder(self, text: str) -> str:
        return (f'<div style="padding:16px;text-align:center;color:{_t(self.t, "text_muted")};'
                f'font-size:13px;border:1px dashed {_t(self.t, "border")};border-radius:6px">'
                f'{esc(text)}</div>')


_BLOCKED_TAGS = re.compile(r"<(script|iframe|object|embed|form)\b[^>]*>.*?</\1>",
                           re.I | re.S)
_ON_ATTR = re.compile(r"\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I)
_STYLE_ATTR = re.compile(r"\sstyle\s*=", re.I)
_BAD_CSS = re.compile(r"(expression|javascript:|url\s*\(\s*['\"]?\s*javascript)", re.I)


def _sanitize_inline_html(raw: str) -> str:
    """极简白名单清洗：允许排版标签与内联 style，剥离脚本/事件/CSS 表达式。"""
    if not raw:
        return ""
    s = _BLOCKED_TAGS.sub("", str(raw))
    s = _ON_ATTR.sub("", s)
    s = re.sub(r"<\s*(script|iframe|object|embed|form|meta|link)[^>]*>", "", s, flags=re.I)

    def _clean_style(m: re.Match) -> str:
        css = m.group(1) or ""
        if _BAD_CSS.search(css):
            return ""
        css = re.sub(r"(position\s*:\s*(absolute|fixed))|(z-index\s*:[^;]*)", "", css, flags=re.I)
        return f' style="{css.strip()}"'

    s = re.sub(r'style\s*=\s*"([^"]*)"', _clean_style, s)
    s = re.sub(r"style\s*=\s*'([^']*)'",
               lambda m: _clean_style(re.match(r'style="([^"]*)"', m.group(1)) or m), s)
    return s.strip()


def render_email(schema: dict, tokens: dict | None = None, **kw) -> str:
    return EmailRenderer(tokens).render(schema, **kw)