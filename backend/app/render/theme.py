"""主题系统：design token → CSS 变量。

单一 token 源同时驱动三处：编辑器预览、导出产物、Mautic 主题。
换肤只改 token，不动组件默认样式。
"""
from __future__ import annotations

from typing import Any

# token 声明：(key, 默认值, 说明, 类型)
TOKEN_SPEC: list[tuple[str, str, str, str]] = [
    ("brand", "#c8102e", "品牌主色（CTA/强调）", "color"),
    ("brand_dark", "#8f0b20", "品牌深色（hover/页脚底）", "color"),
    ("brand_light", "#fdeaed", "品牌浅色（标签/背景）", "color"),
    ("secondary", "#0b1f3a", "辅助深色（Hero/页脚）", "color"),
    ("accent", "#f5a623", "强调色（倒计时/评分）", "color"),
    ("success", "#12a150", "成功", "color"),
    ("warning", "#ffab00", "警告", "color"),
    ("danger", "#e5484d", "错误/售罄", "color"),
    ("text", "#1a1a1a", "正文文字", "color"),
    ("text_muted", "#6b7280", "次要文字", "color"),
    ("text_inverse", "#ffffff", "反色文字", "color"),
    ("bg", "#ffffff", "页面底色", "color"),
    ("bg_subtle", "#f4f5f7", "浅背景（分区）", "color"),
    ("border", "#e5e7eb", "描边", "color"),
    ("radius", "8px", "圆角", "size"),
    ("radius_pill", "999px", "胶囊圆角", "size"),
    ("space_unit", "8px", "间距基数", "size"),
    ("font_family", "system-ui, -apple-system, 'Segoe UI', 'PingFang SC', sans-serif", "字体", "font"),
    ("font_size_base", "16px", "基础字号", "size"),
    ("line_height", "1.6", "行高", "number"),
    ("shadow", "0 1px 3px rgba(0,0,0,0.08)", "阴影", "shadow"),
    ("shadow_lg", "0 8px 24px rgba(0,0,0,0.12)", "大阴影", "shadow"),
    ("email_width", "600px", "邮件内容宽度", "size"),
    ("container_width", "1200px", "页面内容宽度", "size"),
]

TOKEN_KEYS = [t[0] for t in TOKEN_SPEC]
TOKEN_META = {t[0]: {"label": t[2], "type": t[3], "default": t[1]} for t in TOKEN_SPEC}


def var(token: str) -> str:
    return f"--{token}"


def default_tokens() -> dict[str, str]:
    return {k: meta["default"] for k, meta in TOKEN_META.items()}


def merge_tokens(base: dict[str, str] | None, overrides: dict[str, str] | None = None) -> dict[str, str]:
    out = dict(base or default_tokens())
    for k, v in (overrides or {}).items():
        if k in TOKEN_META and v not in (None, ""):
            out[k] = str(v)
    return out


def css_vars(tokens: dict[str, str], *, prefix: str = "--") -> dict[str, str]:
    return {f"{prefix}{k}": v for k, v in tokens.items()}


def tokens_to_css(tokens: dict[str, str], *, selector: str = ":root",
                  comment_header: bool = True) -> str:
    lines: list[str] = []
    if comment_header:
        lines.append("/* design tokens —— 由 Campaign Edit 主题系统生成，请勿手改 */")
    lines.append(f"{selector} {{")
    for k in TOKEN_KEYS:
        v = tokens.get(k, TOKEN_META[k]["default"])
        meta = TOKEN_META[k]
        lines.append(f"  {var(k)}: {v}; /* {meta['label']} */")
    lines.append("}")
    return "\n".join(lines)


def tokens_to_map(tokens: dict[str, str]) -> dict[str, Any]:
    """给前端属性面板用：带 label/type/default 的完整描述。"""
    return {k: {"value": tokens.get(k, m["default"]), "label": m["label"],
                "type": m["type"], "default": m["default"]}
            for k, m in TOKEN_META.items()}


# 内置主题预设
BUILTIN_THEMES: list[dict[str, Any]] = [
    {
        "key": "csts-dark-brand",
        "name": "CSTS 深蓝红（品牌默认）",
        "kind_scope": "all",
        "tokens": {"brand": "#c8102e", "secondary": "#0b1f3a", "accent": "#f5a623"},
    },
    {
        "key": "csts-light-modern",
        "name": "CSTS 浅色现代",
        "kind_scope": "all",
        "tokens": {"brand": "#e11d48", "secondary": "#111827", "bg": "#ffffff",
                   "bg_subtle": "#f8fafc", "radius": "12px", "shadow": "0 2px 8px rgba(17,24,39,0.06)"},
    },
    {
        "key": "football-vivid",
        "name": "赛事活力（高饱和）",
        "kind_scope": "all",
        "tokens": {"brand": "#00a651", "secondary": "#0b1f3a", "accent": "#ffcf00",
                   "brand_light": "#e8f8ef", "radius": "12px"},
    },
    {
        "key": "email-safe-flat",
        "name": "邮件安全扁平",
        "kind_scope": "email",
        "tokens": {"brand": "#0057b8", "secondary": "#001f3f", "radius": "0",
                   "shadow": "none", "font_size_base": "15px", "email_width": "600px"},
    },
]