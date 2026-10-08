"""内置组件：着陆页 / 营销活动站点（campaign）专用块。

与邮件块的关键差异：允许现代 CSS（flex/grid/position），但强制响应式断点参数，
且每个区块都要求能降级（no-JS 可读）。
"""
from __future__ import annotations

from .registry import BlockRegistry

SECTION_PROPS = {
    "bg_color": {"type": "string", "label": "背景色", "default": "transparent"},
    "bg_image": {"type": "string", "label": "背景图", "default": ""},
    "pad_top": {"type": "number", "label": "上间距(px)", "default": 64},
    "pad_bottom": {"type": "number", "label": "下间距(px)", "default": 64},
    "full_bleed": {"type": "boolean", "label": "通栏(突破容器宽度)", "default": False},
}

CHILD_TEXT = [
    "landing.heading", "landing.text", "landing.image", "landing.button",
    "landing.button_group", "landing.ticket_cards", "landing.feature_grid",
    "landing.stat_row", "landing.countdown", "landing.form_embed", "landing.map",
    "landing.faq", "landing.social_proof", "landing.video", "landing.spacer",
]


def register(registry: BlockRegistry) -> None:
    specs: list[dict] = [
        {
            "key": "landing.root", "root_kind": "landing", "name": "页面根容器",
            "kind": ["landing"], "category": "layout_only", "container": True,
            "renderer": "landing_root",
            "props_schema": {
                "content_width": {"type": "string", "label": "内容宽度", "default": "1200px"},
                "bg_color": {"type": "string", "label": "页面底色", "default": "#ffffff"},
                "font_family": {"type": "string", "label": "字体",
                                "default": "system-ui, -apple-system, 'Segoe UI', sans-serif"},
                "lang": {"type": "string", "label": "语言标记", "default": "zh-CN"},
            },
            "style_defaults": {"background_color": "#ffffff"},
        },
        {
            "key": "landing.nav", "name": "导航栏", "kind": ["landing"], "container": True,
            "category": "layout", "renderer": "landing_nav",
            "children_allowed": ["landing.heading", "landing.image", "landing.button"],
            "children_limit": {"max": 10},
            "props_schema": {
                "logo_text": {"type": "string", "label": "Logo 文字", "default": "CSTS"},
                "logo_image": {"type": "string", "label": "Logo 图片", "default": ""},
                "sticky": {"type": "boolean", "label": "吸顶", "default": True},
                "bg_color": {"type": "string", "label": "背景色", "default": "#ffffff"},
                "links": {"type": "array", "label": "菜单", "default": [
                    {"label": "赛程", "href": "#fixtures"},
                    {"label": "票务", "href": "#tickets"},
                    {"label": "指南", "href": "#faq"},
                ]},
            },
            "style_defaults": {"padding": "16px 0", "background_color": "#ffffff"},
        },
        {
            "key": "landing.hero", "name": "首屏 Hero", "kind": ["landing"], "container": True,
            "category": "hero", "renderer": "landing_hero",
            "children_allowed": CHILD_TEXT, "children_limit": {"max": 14},
            "props_schema": {
                **SECTION_PROPS,
                "layout": {"type": "string", "enum": ["centered", "split"], "default": "centered"},
                "min_height": {"type": "string", "label": "最小高度", "default": "560px"},
                "overlay": {"type": "boolean", "label": "遮罩层", "default": True},
                "overlay_color": {"type": "string", "label": "遮罩色", "default": "rgba(0,0,0,0.45)"},
            },
            "style_defaults": {"padding": "80px 0", "background_color": "#0b1f3a"},
        },
        {
            "key": "landing.section", "name": "通用区块", "kind": ["landing"], "container": True,
            "category": "layout", "renderer": "landing_section",
            "children_allowed": CHILD_TEXT, "children_limit": {"max": 30},
            "props_schema": {
                **SECTION_PROPS,
                "anchor": {"type": "string", "label": "锚点 id", "default": ""},
                "container": {"type": "boolean", "label": "使用内容容器", "default": True},
            },
        },
        {
            "key": "landing.heading", "name": "标题", "kind": ["landing"], "container": False,
            "category": "text", "renderer": "landing_heading",
            "props_schema": {
                "text": {"type": "string", "label": "文本", "default": "标题", "required": True},
                "level": {"type": "string", "enum": ["h1", "h2", "h3", "h4"], "default": "h2"},
                "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                "color": {"type": "string", "label": "颜色", "default": ""},
                "max_width": {"type": "string", "label": "最大宽度", "default": ""},
            },
        },
        {
            "key": "landing.text", "name": "段落", "kind": ["landing"], "container": False,
            "category": "text", "renderer": "landing_text",
            "props_schema": {
                "html": {"type": "string", "label": "HTML", "default": "<p>正文内容</p>",
                         "required": True, "editor": "richtext"},
                "align": {"type": "string", "enum": ["left", "center", "right"], "default": "left"},
                "color": {"type": "string", "label": "颜色", "default": ""},
                "font_size": {"type": "string", "label": "字号", "default": "16px"},
                "max_width": {"type": "string", "label": "最大宽度", "default": "720px"},
            },
        },
        {
            "key": "landing.image", "name": "图片", "kind": ["landing"], "container": False,
            "category": "media", "renderer": "landing_image",
            "props_schema": {
                "src": {"type": "string", "label": "图片地址", "default": "", "required": True},
                "alt": {"type": "string", "label": "alt", "default": "", "required": True},
                "width": {"type": "string", "label": "宽度", "default": "100%"},
                "ratio": {"type": "string", "label": "宽高比",
                          "enum": ["auto", "16:9", "4:3", "1:1"], "default": "auto"},
                "loading": {"type": "string", "enum": ["lazy", "eager"], "default": "lazy"},
            },
        },
        {
            "key": "landing.video", "name": "视频（封面+iframe）", "kind": ["landing"],
            "container": False, "category": "media", "renderer": "landing_video",
            "props_schema": {
                "embed_url": {"type": "string", "label": "iframe 地址", "default": ""},
                "poster": {"type": "string", "label": "封面图", "default": ""},
                "autoplay": {"type": "boolean", "label": "自动播放(静音)", "default": False},
                "loop": {"type": "boolean", "label": "循环", "default": False},
            },
        },
        {
            "key": "landing.button", "name": "按钮", "kind": ["landing"], "container": False,
            "category": "action", "renderer": "landing_button",
            "props_schema": {
                "text": {"type": "string", "label": "文案", "default": "立即了解",
                         "required": True},
                "url": {"type": "string", "label": "链接", "default": "#", "required": True},
                "variant": {"type": "string",
                            "enum": ["primary", "secondary", "ghost", "link"], "default": "primary"},
                "size": {"type": "string", "enum": ["sm", "md", "lg"], "default": "md"},
                "track": {"type": "boolean", "label": "埋点 data-track", "default": True},
                "utm_params": {"type": "string", "label": "UTM 参数", "default": ""},
            },
        },
        {
            "key": "landing.button_group", "name": "按钮组", "kind": ["landing"], "container": True,
            "category": "action", "renderer": "landing_button_group",
            "children_allowed": ["landing.button"], "children_limit": {"max": 4},
            "props_schema": {
                "align": {"type": "string", "enum": ["left", "center", "right", "space-between"],
                          "default": "center"},
                "gap": {"type": "number", "label": "间距(px)", "default": 12},
            },
        },
        {
            "key": "landing.countdown", "name": "倒计时", "kind": ["landing"], "container": False,
            "category": "hero", "renderer": "landing_countdown",
            "props_schema": {
                "target": {"type": "string", "label": "目标时间(ISO)", "default": "",
                           "required": True},
                "title": {"type": "string", "label": "标题", "default": "距离开赛"},
                "expired_text": {"type": "string", "label": "过期文案", "default": "比赛已开始"},
            },
        },
        {
            "key": "landing.feature_grid", "name": "特性网格", "kind": ["landing"], "container": False,
            "category": "layout", "renderer": "landing_feature_grid",
            "props_schema": {
                "columns": {"type": "number", "label": "列数(桌面)", "default": 3},
                "items": {"type": "array", "label": "特性项", "default": [
                    {"icon": "🎫", "title": "官方票务", "desc": "直连官方座位图"},
                    {"icon": "🚐", "title": "接送服务", "desc": "含往返接送"},
                    {"icon": "🛡️", "title": "保障", "desc": "官方授权代理"},
                ]},
            },
        },
        {
            "key": "landing.stat_row", "name": "数据条", "kind": ["landing"], "container": False,
            "category": "trust", "renderer": "landing_stat_row",
            "props_schema": {
                "items": {"type": "array", "label": "数据", "default": [
                    {"value": "24", "label": "参赛队"}, {"value": "51", "label": "比赛场次"},
                    {"value": "9", "label": "主办城市"},
                ]},
            },
        },
        {
            "key": "landing.social_proof", "name": "口碑/信任背书", "kind": ["landing"],
            "container": False, "category": "trust", "renderer": "landing_social_proof",
            "props_schema": {
                "rating": {"type": "number", "label": "评分", "default": 4.8},
                "count": {"type": "string", "label": "评价数", "default": "2,300+"},
                "quote": {"type": "string", "label": "推荐语", "default": ""},
                "source": {"type": "string", "label": "来源", "default": "Trustpilot"},
            },
        },
        {
            "key": "landing.ticket_cards", "name": "票务卡片组", "kind": ["landing"],
            "container": False, "category": "commerce", "renderer": "landing_ticket_cards",
            "props_schema": {
                "layout": {"type": "string", "enum": ["grid", "list"], "default": "grid"},
                "cards": {"type": "array", "label": "卡片", "default": [
                    {"name": "标准票", "price": "£89", "old_price": "£110",
                     "desc": "看台坐席", "tag": "热门", "sold_out": False,
                     "url": "https://", "image": ""},
                ]},
            },
        },
        {
            "key": "landing.faq", "name": "常见问题（FAQ）", "kind": ["landing"], "container": False,
            "category": "text", "renderer": "landing_faq",
            "props_schema": {
                "items": {"type": "array", "label": "问答", "default": [
                    {"q": "如何取票？", "a": "现场凭兑换码取票。"},
                    {"q": "可以退票吗？", "a": "赛前 7 天可全额退款。"},
                ]},
                "default_open_first": {"type": "boolean", "label": "默认展开第一项",
                                       "default": True},
            },
        },
        {
            "key": "landing.map", "name": "地图/交通指引", "kind": ["landing"], "container": False,
            "category": "layout", "renderer": "landing_map",
            "props_schema": {
                "title": {"type": "string", "label": "标题", "default": "场馆位置"},
                "address": {"type": "string", "label": "地址", "default": ""},
                "map_embed": {"type": "string", "label": "地图 iframe", "default": ""},
                "note": {"type": "string", "label": "交通提示", "default": ""},
            },
        },
        {
            "key": "landing.form_embed", "name": "嵌入表单", "kind": ["landing"], "container": False,
            "category": "form", "renderer": "landing_form_embed",
            "props_schema": {
                "title": {"type": "string", "label": "标题", "default": "留下你的联系方式"},
                "form_id": {"type": "string", "label": "关联表单内容 ID", "default": "",
                            "required": True},
                "embed_mode": {"type": "string", "enum": ["inline", "modal", "drawer"],
                               "default": "inline"},
                "cta_text": {"type": "string", "label": "弹层按钮文案", "default": ""},
            },
        },
        {
            "key": "landing.spacer", "name": "留白", "kind": ["landing"], "container": False,
            "category": "layout", "renderer": "landing_spacer",
            "props_schema": {"height": {"type": "number", "label": "高度(px)", "default": 48}},
        },
        {
            "key": "landing.footer", "name": "页脚", "kind": ["landing"], "container": True,
            "category": "layout", "renderer": "landing_footer",
            "children_allowed": ["landing.text", "landing.button", "landing.social_links"],
            "children_limit": {"max": 20},
            "props_schema": {
                "columns": {"type": "number", "label": "列数", "default": 4},
                "bg_color": {"type": "string", "label": "背景色", "default": "#0b1f3a"},
                "color": {"type": "string", "label": "文字色", "default": "#c9d1d9"},
                "legal": {"type": "string", "label": "法律声明", "default": ""},
                "privacy_url": {"type": "string", "label": "隐私政策", "default": ""},
                "terms_url": {"type": "string", "label": "服务条款", "default": ""},
            },
            "style_defaults": {"padding": "48px 0", "background_color": "#0b1f3a"},
        },
        {
            "key": "landing.social_links", "name": "社交链接组", "kind": ["landing"],
            "container": False, "category": "social", "renderer": "landing_social_links",
            "props_schema": {
                "items": {"type": "array", "label": "链接", "default": [
                    {"name": "Facebook", "url": "https://facebook.com"},
                    {"name": "Instagram", "url": "https://instagram.com"},
                    {"name": "YouTube", "url": "https://youtube.com"},
                ]},
            },
        },
    ]
    registry.register_many(specs)
    registry.register({
        "key": "landing.root", "root_kind": "landing", "name": "页面根容器",
        "kind": ["landing"], "category": "layout_only", "container": True,
        "renderer": "landing_root", "props_schema": specs[0]["props_schema"],
        "style_defaults": specs[0]["style_defaults"],
    }, root=True, replace=True)