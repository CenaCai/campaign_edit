"""可投递性检查（lint）。

邮件 lint 是**硬门槛**：error 级问题会阻止导出/发布（见 api/v1/contents.py 的 assert_lint_pass）。
规则基于实际送达事故清单，不是泛泛的最佳实践：
 Outlook 砍 position/flex/grid；Gmail 剥离 CSS 变量；Apple Mail 不支持部分现代属性；
 图片缺 alt 影响可访问性与 Gmail 图片策略；无退订链接属合规风险（GDPR/CAN-SPAM）。
"""
from __future__ import annotations

import re
from typing import Any

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


def _issue(code: str, severity: str, message: str, *, node_id: str = "",
            fix: str = "") -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message,
            "node_id": node_id, "fix": fix}


# ---------------------------------------------------------------- email

_EMAIL_BANNED_CSS = [
    (r"position\s*:\s*(absolute|fixed)", "css_position", "position 被 Outlook 忽略，布局会错乱"),
    (r"display\s*:\s*flex", "css_flex", "flex 在 Outlook/部分客户端不支持，请用 table 布局"),
    (r"display\s*:\s*grid", "css_grid", "grid 兼容性差，请用 table 或 inline-block"),
    (r"var\s*\(--", "css_var", "邮件客户端普遍剥离 CSS 变量，请用具体色值"),
    (r"@import", "css_import", "不支持 @import"),
    (r"backdrop-filter", "css_backdrop", "不支持 backdrop-filter"),
    (r"position\s*:\s*sticky", "css_sticky", "不支持 sticky"),
]


def lint_email(schema: dict, html: str) -> dict[str, Any]:
    issues: list[dict] = []
    doc = schema.get("doc") or {}
    root = schema.get("root") or {}
    low = (html or "").lower()

    # 1) CSS 兼容性
    for pattern, code, msg in _EMAIL_BANNED_CSS:
        if re.search(pattern, low):
            issues.append(_issue(code, "error", msg, fix="改用 table 布局 + 具体色值"))

    # 2) 主题行 / 预览文案
    if not (doc.get("subject") or "").strip():
        issues.append(_issue("missing_subject", "error", "缺少邮件主题（subject）",
                             fix="在文档设置里填写主题行"))
    elif len(doc["subject"]) > 60:
        issues.append(_issue("subject_too_long", "warn",
                             f"主题行 {len(doc['subject'])} 字符，移动端可能在 35-40 字后截断",
                             fix="控制在 35 个中文字符以内"))
    if not (doc.get("preheader") or "").strip():
        issues.append(_issue("missing_preheader", "info",
                             "缺少预览文案，客户端会抓取正文首句", fix="填写 preheader"))

    # 3) 合规：退订链接（页脚）
    unsub = bool(re.search(r"退订|unsubscribe", html, re.I))
    if not unsub:
        issues.append(_issue("missing_unsubscribe", "error",
                             "未找到退订链接，违反 GDPR / CAN-SPAM，存在封发风险",
                             fix="添加 email.footer 组件并填写退订链接"))

    # 4) 图片 alt
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    for im in imgs:
        if not re.search(r'alt\s*=\s*"[^"]+"', im, re.I):
            issues.append(_issue("img_no_alt", "warn",
                                 "存在无 alt 的图片，影响可访问性与部分客户端渲染",
                                 fix="为图片补 alt（可为装饰性文字）"))
    if not imgs:
        issues.append(_issue("no_image", "info", "整封邮件没有任何图片"))

    # 5) 链接
    links = re.findall(r'<a\b[^>]*href\s*=\s*"([^"]*)"[^>]*>', html, re.I)
    if not links:
        issues.append(_issue("no_link", "warn", "邮件没有任何链接，无法归因转化"))
    for href in links:
        if not href or href == "#":
            issues.append(_issue("link_empty", "warn", "存在空链接（#）", fix="补齐目标 URL"))
        elif not re.match(r"^(https?://|mailto:|tel:)", href, re.I):
            issues.append(_issue("link_relative", "warn",
                                 f"链接不是绝对地址：{href[:60]}",
                                 fix="邮件里必须使用绝对 URL"))
        elif re.match(r"^javascript:", href, re.I):
            issues.append(_issue("link_js", "error", "存在 javascript: 链接（安全风险）"))

    # 6) 表格布局与宽度
    if "role=\"presentation\"" not in html:
        issues.append(_issue("no_presentation_table", "warn",
                             "未使用 role=presentation 表格，可读性与 Outlook 兼容性下降"))
    width_match = re.search(r"max-width\s*:\s*(\d+)px", html)
    if width_match and int(width_match.group(1)) > 640:
        issues.append(_issue("width_too_wide", "warn",
                             f"内容宽度 {width_match.group(1)}px 偏宽，移动端会横向滚动",
                             fix="建议 600px"))
    if not re.search(r"max-width\s*:\s*\d+px", html):
        issues.append(_issue("no_max_width", "warn", "容器缺少 max-width，移动端不可控"))

    # 7) 响应式与暗色
    if "@media only screen and (max-width" not in html:
        issues.append(_issue("no_media_query", "warn", "缺少移动端 media query"))
    if "<meta name=\"viewport\"" not in html:
        issues.append(_issue("no_viewport", "error", "缺少 viewport meta，移动端会按 980px 缩放"))

    # 8) 正文体量
    text = re.sub(r"<[^>]+>", " ", html)
    chars = len(re.sub(r"\s+", " ", text).strip())
    if chars > 6000:
        issues.append(_issue("too_long", "warn", f"正文约 {chars} 字符，截断风险高"))
    if chars < 50:
        issues.append(_issue("too_short", "info", "正文内容过少，可能是空模板"))

    # 9) 编码
    if "<meta charset" not in html.lower():
        issues.append(_issue("no_charset", "error", "缺少 charset 声明，中文可能乱码"))

    # 10) 已存在邮件里的空组件
    if _placeholder_left(html):
        issues.append(_issue("placeholder_left", "warn",
                             "仍有未替换的占位提示文案（如「在此输入内容」）",
                             fix="补齐内容后再发送"))

    return _summarize(issues, kind="email", html=html)


def _placeholder_left(html: str) -> bool:
    return bool(re.search(r"在此输入内容|请在首屏添加|空列|标题</", html or ""))


# ---------------------------------------------------------------- form

def lint_form(schema: dict, html: str) -> dict[str, Any]:
    issues: list[dict] = []
    root = schema.get("root") or {}
    p = root.get("props") or {}

    if not (p.get("action") or "").strip():
        issues.append(_issue("no_action", "warn",
                             "未配置提交地址(action)，表单只能回落到当前页",
                             fix="填入 endpoint，或配置 Mautic form ID"))
    if not (p.get("form_name") or "").strip():
        issues.append(_issue("no_form_name", "warn", "未填写表单名，数据侧难以归因"))

    fields = re.findall(r'data-field="([^"]+)"', html)
    if not fields:
        issues.append(_issue("no_fields", "error", "表单没有任何字段"))
    if len(fields) != len(set(fields)):
        dup = [f for f in set(fields) if fields.count(f) > 1]
        issues.append(_issue("duplicate_field", "error",
                             f"字段名重复：{', '.join(dup)}", fix="字段名必须唯一"))
    # honeypot 之外还需真实验证：提示后端校验
    if "ce-hp" not in html and "recaptcha" not in html.lower():
        issues.append(_issue("no_antispam", "info", "没有反垃圾机制，建议启用 honeypot"))
    for kw in ("隐私政策", "privacy"):
        if kw not in html:
            issues.append(_issue("no_privacy_link", "warn",
                                 "页面未展示隐私政策链接（GDPR 要求）",
                                 fix="添加 form.consent_field 组件"))
            break
    if not p.get("mautic_form_id") and not p.get("submit_ajax", True):
        issues.append(_issue("no_ajax", "info",
                             "非 AJAX 提交会跳转页面，无法就地展示成功提示"))
    if "<label" not in html:
        issues.append(_issue("no_label", "error", "缺少 label 关联，无障碍不达标"))
    return _summarize(issues, kind="form", html=html)


# ---------------------------------------------------------------- landing

def lint_landing(schema: dict, html: str) -> dict[str, Any]:
    issues: list[dict] = []
    doc = schema.get("doc") or {}
    if not (doc.get("name") or "").strip():
        issues.append(_issue("no_title", "error", "缺少页面标题（<title>）"))
    if not (doc.get("description") or "").strip():
        issues.append(_issue("no_meta_desc", "info",
                             "缺少 meta description，影响搜索与社交分享"))
    for meta in ('property="og:title"', 'property="og:type"', 'name="viewport"'):
        if meta not in html:
            issues.append(_issue("no_seo_meta", "warn", f"缺少 {meta}"))
    if "<h1" not in html:
        issues.append(_issue("no_h1", "warn", "页面缺少 h1，SEO 与语义不完整"))
    links = re.findall(r'<a\b[^>]*href\s*=\s*"([^"]*)"', html, re.I)
    cta = [h for h in links if re.search(r"购票|报名|立即|download|ticket|sign", h, re.I)]
    if not cta:
        issues.append(_issue("no_cta", "warn", "页面没有明显的行动号召(CTA)链接"))
    for h in links:
        if h.startswith("#") and len(h) <= 2:
            issues.append(_issue("empty_anchor", "info", "存在指向页内的空锚点"))
    if "alt=" not in html:
        issues.append(_issue("img_no_alt", "warn", "图片缺少 alt"))
    if "viewport" in html and "@media (max-width" not in html:
        issues.append(_issue("not_responsive", "error", "缺少响应式断点，移动端不可用"))
    # 埋点
    if "data-track" not in html and "gtag" not in html and "dataLayer" not in html:
        issues.append(_issue("no_tracking", "info", "未配置 CTA 埋点，无法评估转化"))
    return _summarize(issues, kind="landing", html=html)


def _summarize(issues: list[dict], *, kind: str, html: str) -> dict[str, Any]:
    counts = {"error": 0, "warn": 0, "info": 0}
    for i in issues:
        counts[i["severity"]] = counts.get(i["severity"], 0) + 1
    issues.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 9))
    return {
        "kind": kind,
        "issues": issues,
        "counts": counts,
        "passed": counts["error"] == 0,
        "score": max(0, 100 - counts["error"] * 20 - counts["warn"] * 5 - counts["info"] * 1),
        "html_size": len(html or ""),
    }


def lint(schema: dict, html: str, kind: str | None = None) -> dict[str, Any]:
    kind = kind or schema.get("kind")
    if kind == "email":
        return lint_email(schema, html)
    if kind == "form":
        return lint_form(schema, html)
    return lint_landing(schema, html)


def lint_generic(schema: dict, html: str) -> dict[str, Any]:
    """所有类型都跑的基础安全检查。"""
    issues: list[dict] = []
    low = (html or "").lower()
    if "<script" in low:
        if re.search(r"<script[^>]*src\s*=\s*[\"']?javascript:", low):
            issues.append(_issue("script_js_src", "error", "存在 javascript: 脚本源"))
    if re.search(r"\son\w+\s*=", html or ""):
        issues.append(_issue("inline_handler", "info",
                             "存在内联事件属性（onclick 等），确认是刻意为之"))
    if "<style" not in low:
        issues.append(_issue("no_style", "info", "没有 <style> 块，样式可能全靠内联"))
    return _summarize(issues, kind=schema.get("kind") or "generic", html=html)


def merge(*results: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict] = []
    for r in results:
        issues.extend(r.get("issues") or [])
    kind = results[0].get("kind") if results else "generic"
    html = results[0].get("html", "") if results else ""
    return _summarize(issues, kind=kind, html=html)