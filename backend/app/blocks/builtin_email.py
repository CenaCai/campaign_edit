"""内置组件：HTML 邮件专用块。

邮件渲染约束（渲染器已强制，此处定义只是第一道防线）：
* 表格布局 + inline CSS，宽度靠 600px 容器；
* 不支持 position / flex / grid / 伪元素；
* 所有图片必须带 alt；
* 按钮用 table + VML 兜底，不用 border-radius 以外的现代属性。
"""
from __future__ import annotations

from .registry import BlockRegistry

TEXT_STYLE = {"padding": "0", "color": "#1a1a1a", "font_size": "16px", "line_height": "1.6"}


def register(registry: BlockRegistry) -> None:
    specs: list[dict] = [
        {
            "key": "email.root", "root_kind": "email", "name": "邮件根容器",
            "kind": ["email"], "category": "layout_only", "container": True,
            "renderer": "email_root", "source": "builtin",
            "props_schema": {
                "width": {"type": "string", "label": "内容宽度", "default": "600px"},
                "bg_color": {"type": "string", "label": "背景色", "default": "#f4f5f7"},
                "align": {"type": "string", "label": "水平对齐",
                          "enum": ["left", "center", "right"], "default": "center"},
            },
            "style_defaults": {"background_color": "#f4f5f7"},
        },
        {
            "key": "email.header", "name": "邮件头部（Logo/标题条）", "kind": ["email"],
            "category": "layout", "container": True, "renderer": "email_header",
            "children_allowed": ["email.text", "email.image"],
            "children_limit": {"max": 4},
            "props_schema": {
                "logo_url": {"type": "string", "label": "Logo URL", "default": ""},
                "logo_height": {"type": "number", "label": "Logo 高度(px)", "default": 40},
                "bg_color": {"type": "string", "label": "背景色", "default": "#ffffff"},
                "align": {"type": "string", "label": "对齐",
                          "enum": ["left", "center", "right"], "default": "left"},
                "alt": {"type": "string", "label": "Logo alt", "default": "Logo"},
            },
            "style_defaults": {"padding": "24px", "background_color": "#ffffff"},
        },
        {
            "key": "email.hero", "name": "首屏横幅", "kind": ["email"], "container": True,
            "category": "hero", "renderer": "email_hero",
            "children_allowed": ["email.text", "email.button"],
            "children_limit": {"max": 6},
            "props_schema": {
                "bg_color": {"type": "string", "label": "背景色", "default": "#0b1f3a"},
                "bg_image": {"type": "string", "label": "背景图 URL", "default": ""},
                "pad_top": {"type": "number", "label": "上内边距(px)", "default": 40},
                "pad_bottom": {"type": "number", "label": "下内边距(px)", "default": 40},
            },
            "style_defaults": {"padding": "40px 32px", "background_color": "#0b1f3a"},
        },
        {
            "key": "email.text", "name": "富文本段落", "kind": ["email"], "container": True,
            "category": "text", "renderer": "email_text",
            "children_allowed": ["email.text", "email.button"],
            "children_limit": {"max": 20},
            "props_schema": {
                "html": {"type": "string", "label": "HTML 内容", "default": "<p>在此输入内容</p>",
                         "required": True, "editor": "richtext"},
                "font_size": {"type": "string", "label": "字号", "default": "16px"},
                "color": {"type": "string", "label": "文字色", "default": "#1a1a1a"},
                "line_height": {"type": "string", "label": "行高", "default": "1.6"},
                "align": {"type": "string", "label": "对齐",
                          "enum": ["left", "center", "right"], "default": "left"},
                "pad": {"type": "string", "label": "内边距", "default": "16px"},
            },
            "style_defaults": TEXT_STYLE,
        },
        {
            "key": "email.heading", "name": "标题", "kind": ["email"], "container": False,
            "category": "text", "renderer": "email_heading",
            "props_schema": {
                "text": {"type": "string", "label": "文本", "default": "标题", "required": True},
                "level": {"type": "string", "label": "层级",
                          "enum": ["h1", "h2", "h3"], "default": "h2"},
                "color": {"type": "string", "label": "颜色", "default": "#0b1f3a"},
                "align": {"type": "string", "label": "对齐",
                          "enum": ["left", "center", "right"], "default": "left"},
            },
        },
        {
            "key": "email.image", "name": "图片", "kind": ["email"], "container": False,
            "category": "media", "renderer": "email_image",
            "props_schema": {
                "src": {"type": "string", "label": "图片 URL", "default": "", "required": True},
                "alt": {"type": "string", "label": "alt 文本（无障碍必填）", "default": "",
                        "required": True},
                "width": {"type": "string", "label": "宽度", "default": "560px"},
                "href": {"type": "string", "label": "跳转链接", "default": ""},
                "radius": {"type": "string", "label": "圆角", "default": "0"},
            },
        },
        {
            "key": "email.button", "name": "按钮（CTA）", "kind": ["email"], "container": False,
            "category": "action", "renderer": "email_button",
            "props_schema": {
                "text": {"type": "string", "label": "按钮文案", "default": "立即查看",
                         "required": True},
                "url": {"type": "string", "label": "链接", "default": "https://",
                        "required": True},
                "bg_color": {"type": "string", "label": "按钮底色", "default": "#c8102e"},
                "text_color": {"type": "string", "label": "按钮文字色", "default": "#ffffff"},
                "size": {"type": "string", "label": "尺寸",
                         "enum": ["sm", "md", "lg"], "default": "md"},
                "full_width": {"type": "boolean", "label": "通栏", "default": False},
                "utm_params": {"type": "string", "label": "UTM 参数（a=b&c=d）", "default": ""},
            },
        },
        {
            "key": "email.button_group", "name": "按钮组", "kind": ["email"], "container": True,
            "category": "action", "renderer": "email_button_group",
            "children_allowed": ["email.button"], "children_limit": {"max": 3},
            "props_schema": {"align": {"type": "string", "enum": ["left", "center", "right"],
                                       "default": "center"}},
        },
        {
            "key": "email.columns", "name": "多列布局（≤3）", "kind": ["email"], "container": True,
            "category": "layout", "renderer": "email_columns",
            "children_allowed": ["email.column"], "children_limit": {"max": 3},
            "props_schema": {
                "gap": {"type": "number", "label": "列间距(px)", "default": 16},
                "bg_color": {"type": "string", "label": "背景色", "default": ""},
            },
        },
        {
            "key": "email.column", "name": "列", "kind": ["email"], "container": True,
            "category": "layout", "renderer": "email_column",
            "children_allowed": ["email.text", "email.image", "email.heading",
                                 "email.button", "email.product_card", "email.ticket_card"],
            "children_limit": {"max": 12},
            "props_schema": {
                "span": {"type": "number", "label": "占宽(1-3)", "default": 1},
                "align": {"type": "string", "enum": ["left", "center", "right", "top"],
                          "default": "top"},
                "bg_color": {"type": "string", "label": "背景色", "default": ""},
            },
        },
        {
            "key": "email.divider", "name": "分隔线", "kind": ["email"], "container": False,
            "category": "layout", "renderer": "email_divider",
            "props_schema": {
                "color": {"type": "string", "label": "颜色", "default": "#e5e7eb"},
                "thickness": {"type": "number", "label": "粗细(px)", "default": 1},
            },
        },
        {
            "key": "email.spacer", "name": "留白", "kind": ["email"], "container": False,
            "category": "layout", "renderer": "email_spacer",
            "props_schema": {"height": {"type": "number", "label": "高度(px)", "default": 24}},
        },
        {
            "key": "email.product_card", "name": "商品/服务卡", "kind": ["email"], "container": False,
            "category": "commerce", "renderer": "email_product_card",
            "props_schema": {
                "title": {"type": "string", "label": "标题", "default": "服务名称",
                          "required": True},
                "desc": {"type": "string", "label": "描述", "default": ""},
                "price": {"type": "string", "label": "价格", "default": "£0"},
                "old_price": {"type": "string", "label": "划线价", "default": ""},
                "image": {"type": "string", "label": "图片", "default": ""},
                "url": {"type": "string", "label": "链接", "default": ""},
                "badge": {"type": "string", "label": "角标", "default": ""},
                "align": {"type": "string", "enum": ["left", "center"], "default": "left"},
            },
        },
        {
            "key": "email.ticket_card", "name": "票务卡片（赛事）", "kind": ["email"], "container": False,
            "category": "commerce", "renderer": "email_ticket_card",
            "props_schema": {
                "event_name": {"type": "string", "label": "赛事名称", "default": "赛事名称",
                               "required": True},
                "date": {"type": "string", "label": "日期", "default": ""},
                "venue": {"type": "string", "label": "场馆", "default": ""},
                "price_from": {"type": "string", "label": "起价", "default": "£0"},
                "url": {"type": "string", "label": "购票链接", "default": ""},
                "sold_out": {"type": "boolean", "label": "显示售罄", "default": False},
            },
        },
        {
            "key": "email.countdown", "name": "赛事倒计时（静态渲染）", "kind": ["email"],
            "container": False, "category": "hero", "renderer": "email_countdown",
            "props_schema": {
                "target": {"type": "string", "label": "目标时间(ISO)", "default": "",
                           "required": True},
                "title": {"type": "string", "label": "标题", "default": "距离开赛"},
                "bg_color": {"type": "string", "label": "背景色", "default": "#0b1f3a"},
                "color": {"type": "string", "label": "文字色", "default": "#ffffff"},
            },
        },
        {
            "key": "email.social", "name": "社交图标行", "kind": ["email"], "container": False,
            "category": "social", "renderer": "email_social",
            "props_schema": {
                "icons": {"type": "array", "label": "图标", "default": [
                    {"name": "Facebook", "url": "https://facebook.com"},
                    {"name": "Instagram", "url": "https://instagram.com"},
                    {"name": "YouTube", "url": "https://youtube.com"},
                ]},
                "color": {"type": "string", "label": "颜色", "default": "#4b5563"},
            },
        },
        {
            "key": "email.footer", "name": "页脚（含退订）", "kind": ["email"], "container": True,
            "category": "layout", "renderer": "email_footer",
            "children_allowed": ["email.text"], "children_limit": {"max": 8},
            "props_schema": {
                "company": {"type": "string", "label": "公司名", "default": "Connexus Travel"},
                "address": {"type": "string", "label": "公司地址（合规必填）", "default": ""},
                "unsubscribe_url": {"type": "string", "label": "退订链接", "default": ""},
                "unsubscribe_text": {"type": "string", "label": "退订文案", "default": "退订"},
                "preferences_url": {"type": "string", "label": "偏好设置链接", "default": ""},
                "bg_color": {"type": "string", "label": "背景色", "default": "#0b1f3a"},
                "color": {"type": "string", "label": "文字色", "default": "#c9d1d9"},
            },
            "style_defaults": {"padding": "24px", "background_color": "#0b1f3a"},
        },
    ]
    registry.register_many(specs, root=False)
    # 根容器单独注册（覆盖通用默认值）
    registry.register({
        "key": "email.root", "root_kind": "email", "name": "邮件根容器",
        "kind": ["email"], "category": "layout_only", "container": True,
        "renderer": "email_root", "props_schema": specs[0]["props_schema"],
        "style_defaults": specs[0]["style_defaults"],
    }, root=True, replace=True)