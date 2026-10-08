"""内置模板库：三类内容 × 主要营销场景。

模板即 Block Schema。标签用中文业务词，直接参与意图匹配打分
（见 intent/service.py::_score_template），所以 tags 不是装饰，是检索入口。
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------- 邮件模板

def _email(name: str, body: list[dict], *, footer: bool = True) -> dict[str, Any]:
    children: list[dict] = [{
        "id": "h", "type": "email.header", "props": {"logo_url": "", "logo_height": 36,
                                                     "align": "left", "alt": "CSTS"},
        "style": {}, "children": [],
    }, *body]
    if footer:
        children.append({
            "id": "f", "type": "email.footer",
            "props": {"company": "Connexus Travel Sports", "address": "London, United Kingdom",
                       "unsubscribe_url": "{{unsubscribe_url}}", "unsubscribe_text": "退订",
                       "preferences_url": "{{preferences_url}}"},
            "style": {},
            "children": [{"id": "ft", "type": "email.text", "props": {
                "html": "<p>你收到这封邮件是因为订阅了 CSTS 赛事资讯。</p>",
                "font_size": "12px", "color": "#c9d1d9", "align": "center"},
                "style": {"padding": "0"}, "children": []}],
        })
    return {"kind": "email", "root": {"id": "root", "type": "email.root",
                                      "props": {"width": "600px", "bg_color": "#f4f5f7",
                                                "align": "center"},
                                      "style": {}, "children": children}}


EMAIL_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "EM_PROMO_VOUCHER", "name": "促销发券（含折扣与倒计时）", "kind": "email",
        "scenario": "promo", "tags": ["促销", "发券", "折扣", "优惠", "限时", "倒计时", "voucher", "coupon"],
        "description": "主推折扣券：Hero + 券码卡 + 紧迫感倒计时 + 双 CTA + 合规页脚",
        "schema": _email("促销发券", [
            {"id": "hero", "type": "email.hero",
             "props": {"bg_color": "#0b1f3a", "pad_top": 40, "pad_bottom": 36},
             "style": {}, "children": [
                 {"id": "h1", "type": "email.heading",
                  "props": {"text": "会员专享 · 20% OFF", "level": "h1", "color": "#ffffff",
                            "align": "center"}, "style": {}},
                 {"id": "t1", "type": "email.text", "props": {
                     "html": "<p style='margin:8px 0 0'>新赛季套票限时折扣，今天结束</p>",
                     "color": "#c9d1d9", "align": "center", "font_size": "15px"},
                  "style": {"padding": "0"}, "children": []}]},
            {"id": "cd", "type": "email.countdown", "props": {
                "target": "2026-12-31T23:59:59+01:00", "title": "距折扣结束"},
             "style": {}},
            {"id": "card", "type": "email.product_card", "props": {
                "title": "2026/27 赛季套票（季票）", "desc": "含主场 20 场 + 优先购票权",
                "price": "£199", "old_price": "£249", "badge": "省 £50", "align": "center",
                "url": "https://example.com/season-ticket"}, "style": {}},
            {"id": "d", "type": "email.divider", "props": {}, "style": {}},
            {"id": "bg", "type": "email.button_group", "props": {"align": "center"},
             "style": {}, "children": [
                 {"id": "b1", "type": "email.button", "props": {
                     "text": "立即使用优惠券", "url": "https://example.com/redeem",
                     "bg_color": "#c8102e", "size": "lg",
                     "utm_params": "utm_source=email&utm_campaign=promo_voucher"}, "style": {}},
                 {"id": "b2", "type": "email.button", "props": {
                     "text": "查看全部赛事", "url": "https://example.com/events",
                     "bg_color": "#ffffff", "text_color": "#0b1f3a", "size": "lg"},
                  "style": {}}]},
            {"id": "t2", "type": "email.text", "props": {
                "html": "<p style='margin:0;font-size:12px;color:#6b7280'>券码：<b>WATERBOMB20</b>，"
                        "每单满 £100 可用，不与其他优惠叠加。</p>", "align": "center"},
             "style": {"padding": "8px 32px"}, "children": []},
        ]),
    },
    {
        "key": "EM_EVENT_INVITE", "name": "赛事邀请 + 倒计时", "kind": "email",
        "scenario": "event", "tags": ["赛事", "邀请", "开赛", "门票", "倒计时", "match", "ticket"],
        "description": "赛前邀约：赛事信息 + 场馆 + 票种卡片 + 倒计时",
        "schema": _email("赛事邀请", [
            {"id": "hero", "type": "email.hero", "props": {"bg_color": "#062033"},
             "style": {}, "children": [
                 {"id": "h1", "type": "email.heading", "props": {
                     "text": "EURO 2028 · 小组赛", "level": "h1", "color": "#ffffff",
                     "align": "center"}, "style": {}},
                 {"id": "t1", "type": "email.text", "props": {
                     "html": "<p style='margin:6px 0 0'>英格兰 vs 法国 · 2026-06-15 19:00 · Wembley Stadium</p>",
                     "color": "#c9d1d9", "align": "center", "font_size": "15px"},
                  "style": {"padding": "0"}, "children": []}]},
            {"id": "cd", "type": "email.countdown", "props": {
                "target": "2026-06-15T18:00:00+01:00", "title": "距离开赛"}, "style": {}},
            {"id": "tk", "type": "email.ticket_card", "props": {
                "event_name": "England vs France", "date": "2026-06-15 19:00",
                "venue": "Wembley Stadium, London", "price_from": "£89"}, "style": {}},
            {"id": "tk2", "type": "email.ticket_card", "props": {
                "event_name": "England vs Spain", "date": "2026-06-20 15:00",
                "venue": "Old Trafford, Manchester", "price_from": "£79",
                "sold_out": True}, "style": {}},
            {"id": "b1", "type": "email.button", "props": {
                "text": "查看全部票档", "url": "https://example.com/tickets", "size": "lg",
                "full_width": False}, "style": {}},
        ]),
    },
    {
        "key": "EM_SCHEDULE_CHANGE", "name": "赛程改期/取消通知", "kind": "email",
        "scenario": "schedule_change", "tags": ["改期", "取消", "延期", "时间变更", "通知", "紧急"],
        "description": "高优先级变更通知：醒目变更卡 + 新旧时间对照 + 补救措施 + 支持入口",
        "schema": _email("赛程变更", [
            {"id": "h1", "type": "email.heading", "props": {
                "text": "重要：比赛时间变更通知", "level": "h1", "color": "#c8102e",
                "align": "center"}, "style": {}},
            {"id": "t1", "type": "email.text", "props": {
                "html": "<p>我们很抱歉地通知您，原定于 <b>2026-07-18 15:00</b> 的比赛"
                        "现调整至下述时间。您的门票已自动顺延，无需任何操作。</p>",
                "align": "left"}, "style": {}},
            {"id": "col", "type": "email.columns", "props": {"gap": 16}, "style": {},
             "children": [
                 {"id": "c1", "type": "email.column", "props": {"span": 1, "bg_color": "#f4f5f7"},
                  "style": {}, "children": [
                      {"id": "l", "type": "email.heading", "props": {
                          "text": "原定", "level": "h3", "color": "#6b7280", "align": "center"},
                       "style": {}},
                      {"id": "v", "type": "email.text", "props": {
                          "html": "<p style='text-align:center;text-decoration:line-through;"
                                  "margin:0;color:#6b7280'>7月18日 15:00</p>", "align": "center"},
                       "style": {"padding": "0 12px"}, "children": []}]},
                 {"id": "c2", "type": "email.column", "props": {"span": 1, "bg_color": "#fdeaed"},
                  "style": {}, "children": [
                      {"id": "l2", "type": "email.heading", "props": {
                          "text": "调整后", "level": "h3", "color": "#c8102e", "align": "center"},
                       "style": {}},
                      {"id": "v2", "type": "email.text", "props": {
                          "html": "<p style='text-align:center;margin:0;font-weight:700;"
                                  "color:#c8102e'>7月20日 19:00</p>", "align": "center"},
                       "style": {"padding": "0 12px"}, "children": []}]}]},
            {"id": "b1", "type": "email.button", "props": {
                "text": "查看新赛程", "url": "https://example.com/new-fixture",
                "bg_color": "#c8102e", "size": "lg"}, "style": {}},
            {"id": "t2", "type": "email.text", "props": {
                "html": "<p>如无法出席新时间，可在 <a href='https://example.com/refund'>退款页面</a> "
                        "申请全额退款，或联系客服 020 7946 0000。</p>", "align": "center"},
             "style": {}, "children": []},
        ]),
    },
    {
        "key": "EM_ABANDON_CART", "name": "弃单挽回（加时提醒）", "kind": "email",
        "scenario": "abandon", "tags": ["弃单", "未支付", "购物车", "挽回", "提醒", "cart"],
        "description": "24h 未支付提醒：商品摘要 + 库存紧张 + 一键回到结算",
        "schema": _email("弃单挽回", [
            {"id": "h1", "type": "email.heading", "props": {
                "text": "你的订单还在等你", "level": "h1", "color": "#0b1f3a"}, "style": {}},
            {"id": "t1", "type": "email.text", "props": {
                "html": "<p>你在 CSTS 选择的门票尚未完成支付，座位保留 <b>23 小时 59 分</b>。</p>"},
             "style": {}},
            {"id": "card", "type": "email.product_card", "props": {
                "title": "England vs France · 看台票", "desc": "Wembley Stadium · 2026-06-15 19:00",
                "price": "£89", "badge": "仅剩 12 张"}, "style": {}},
            {"id": "b1", "type": "email.button", "props": {
                "text": "继续完成支付", "url": "https://example.com/checkout",
                "bg_color": "#c8102e", "size": "lg", "full_width": True}, "style": {}},
            {"id": "t2", "type": "email.text", "props": {
                "html": "<p style='font-size:13px;color:#6b7280'>需要帮助？回复本邮件即可联系我们。</p>",
                "align": "center"}, "style": {}, "children": []},
        ]),
    },
    {
        "key": "EM_RECOVERY", "name": "流失挽回（专属优惠）", "kind": "email",
        "scenario": "recovery", "tags": ["流失", "挽回", "召回", "唤醒", "专属", "优惠"],
        "description": "90 天未活跃订阅者：专属折扣 + 新赛季亮点 + 退订合规",
        "schema": _email("流失挽回", [
            {"id": "hero", "type": "email.hero", "props": {"bg_color": "#0b1f3a"},
             "style": {}, "children": [
                 {"id": "h1", "type": "email.heading", "props": {
                     "text": "我们想你了", "level": "h1", "color": "#ffffff",
                     "align": "center"}, "style": {}},
                 {"id": "t1", "type": "email.text", "props": {
                     "html": "<p style='margin:6px 0 0'>专属回归礼：首单 £10 折扣</p>",
                     "color": "#c9d1d9", "align": "center"}, "style": {"padding": "0"},
                  "children": []}]},
            {"id": "b1", "type": "email.button", "props": {
                "text": "领取 £10 折扣", "url": "https://example.com/winback",
                "bg_color": "#f5a623", "text_color": "#0b1f3a", "size": "lg"},
             "style": {}},
            {"id": "col", "type": "email.columns", "props": {"gap": 16}, "style": {},
             "children": [
                 {"id": "c1", "type": "email.column", "props": {"span": 1}, "style": {},
                  "children": [{"id": "t", "type": "email.heading", "props": {
                      "text": "新赛季", "level": "h3", "align": "center"}, "style": {}}]},
                 {"id": "c2", "type": "email.column", "props": {"span": 1}, "style": {},
                  "children": [{"id": "t2", "type": "email.heading", "props": {
                      "text": "专属接送", "level": "h3", "align": "center"}, "style": {}}]}]},
        ]),
    },
    {
        "key": "EM_WELCOME", "name": "欢迎邮件（注册成功）", "kind": "email",
        "scenario": "welcome", "tags": ["欢迎", "新客", "注册", "入会", "onboarding"],
        "description": "欢迎 + 首次优惠 + 后续三步引导",
        "schema": _email("欢迎邮件", [
            {"id": "hero", "type": "email.hero", "props": {"bg_color": "#0a5f45"},
             "style": {}, "children": [
                 {"id": "h1", "type": "email.heading", "props": {
                     "text": "欢迎加入 CSTS", "level": "h1", "color": "#ffffff",
                     "align": "center"}, "style": {}}]},
            {"id": "t1", "type": "email.text", "props": {
                "html": "<p>Hi {{contact.firstname|default:'球友'}}，欢迎加入 CSTS。"
                        "注册成功即赠 <b>£15 新客礼券</b>，30 天内有效。</p>", "align": "center"},
             "style": {}},
            {"id": "card", "type": "email.product_card", "props": {
                "title": "新客礼券 £15", "desc": "满 £80 可用｜注册赠送", "price": "£15",
                "badge": "新客专享", "align": "center"}, "style": {}},
            {"id": "b1", "type": "email.button", "props": {
                "text": "开始浏览赛事", "url": "https://example.com/events", "size": "lg"},
             "style": {}},
            {"id": "d", "type": "email.divider", "props": {}, "style": {}},
            {"id": "t2", "type": "email.text", "props": {
                "html": "<p><b>接下来三步：</b><br/>1. 完善偏好，收到你关注的赛事<br/>"
                        "2. 加入会员，获取优先购票权<br/>3. 下载 App，随时查看电子票</p>"},
             "style": {}, "children": []},
        ]),
    },
    {
        "key": "EM_NEWSLETTER", "name": "赛事周报简报", "kind": "email",
        "scenario": "newsletter", "tags": ["周报", "资讯", "简报", "newsletter", "赛程"],
        "description": "多列卡片式周报：本周焦点 + 赛程列表 + 社媒",
        "schema": _email("赛事周报", [
            {"id": "h1", "type": "email.heading", "props": {
                "text": "本周赛事速递", "level": "h1"}, "style": {}},
            {"id": "t1", "type": "email.text", "props": {
                "html": "<p>2026 年第 42 周 · 3 场焦点战 + 2 场季票开售</p>", "align": "left"},
             "style": {}},
            {"id": "col", "type": "email.columns", "props": {"gap": 16}, "style": {},
             "children": [
                 {"id": "c1", "type": "email.column", "props": {"span": 1}, "style": {},
                  "children": [{"id": "card1", "type": "email.product_card", "props": {
                      "title": "England vs Brazil", "desc": "周六 15:00 · Wembley",
                      "price": "£79", "url": "https://example.com/m1"}, "style": {}}]},
                 {"id": "c2", "type": "email.column", "props": {"span": 1}, "style": {},
                  "children": [{"id": "card2", "type": "email.product_card", "props": {
                      "title": "季票开售", "desc": "会员优先 48 小时", "price": "£199",
                      "badge": "即将开售"}, "style": {}}]}]},
            {"id": "soc", "type": "email.social", "props": {}, "style": {}},
        ]),
    },
]


# ---------------------------------------------------------------- 表单模板

def _form(name: str, fields: list[dict], *, root_props: dict | None = None) -> dict[str, Any]:
    props = {"form_name": name, "submit_label": "提交",
             "success_message": "提交成功，我们会尽快与你联系。",
             "action": "", "method": "POST", "submit_ajax": True,
             "layout": "two_col", "theme_color": "#c8102e"}
    props.update(root_props or {})
    return {"kind": "form", "root": {"id": "root", "type": "form.root", "props": props,
                                     "style": {}, "children": fields}}


FORM_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "FORM_LEAD_GEN", "name": "标准留资表单（两列）", "kind": "form",
        "scenario": "lead_gen",
        "tags": ["留资", "报名", "表单", "线索", "姓名", "邮箱", "手机号", "咨询", "lead"],
        "description": "最通用：姓名/邮箱/电话/国家/票种 + 隐私同意。两列布局，转化率高",
        "schema": _form("标准留资", [
            {"id": "h", "type": "form.heading", "props": {
                "text": "留下你的联系方式", "level": "h2", "align": "left"}, "style": {}},
            {"id": "s", "type": "form.section", "props": {"title": "", "description": ""},
             "style": {}, "children": [
                 {"id": "f1", "type": "form.text_field", "props": {
                     "label": "名", "name": "firstname", "required": True, "width": "half",
                     "placeholder": "Jane"}, "style": {}},
                 {"id": "f2", "type": "form.text_field", "props": {
                     "label": "姓", "name": "lastname", "required": True, "width": "half",
                     "placeholder": "Smith"}, "style": {}},
                 {"id": "f3", "type": "form.email_field", "props": {
                     "label": "邮箱", "name": "email", "required": True, "width": "full",
                     "mautic_field": "email"}, "style": {}},
                 {"id": "f4", "type": "form.phone_field", "props": {
                     "label": "手机号", "name": "phone", "required": True, "width": "half",
                     "country_code": "UK", "mautic_field": "phone"}, "style": {}},
                 {"id": "f5", "type": "form.select_field", "props": {
                     "label": "国家", "name": "country", "required": True, "width": "half",
                     "options": [{"label": "United Kingdom", "value": "GB"},
                                 {"label": "United States", "value": "US"},
                                 {"label": "China", "value": "CN"},
                                 {"label": "Other", "value": "OTHER"}],
                     "mautic_field": "country"}, "style": {}},
                 {"id": "f6", "type": "form.select_field", "props": {
                     "label": "感兴趣的赛事", "name": "event_interest", "required": False,
                     "width": "full",
                     "options": [{"label": "足球", "value": "football"},
                                 {"label": "篮球", "value": "basketball"},
                                 {"label": "综合赛事通票", "value": "multi"}]}, "style": {}},
                 {"id": "f7", "type": "form.textarea_field", "props": {
                     "label": "留言", "name": "message", "required": False, "width": "full",
                     "rows": 3}, "style": {}},
                 {"id": "hp", "type": "form.captcha", "props": {
                     "provider": "honeypot"}, "style": {}},
                 {"id": "cs", "type": "form.consent_field", "props": {
                     "label": "我已阅读并同意隐私政策", "policy_url": "https://example.com/privacy",
                     "required": True, "marketing_consent": True,
                     "consent_text": "我同意接收赛事资讯与优惠信息（可随时退订）"}, "style": {}}]},
            {"id": "sub", "type": "form.submit", "props": {
                "label": "提交", "variant": "primary", "block": True}, "style": {}},
        ]),
    },
    {
        "key": "FORM_EVENT_REG", "name": "赛事报名表（分组）", "kind": "form",
        "scenario": "event",
        "tags": ["赛事", "报名", "注册", "分组", "票种", "人数", "attendee", "registration"],
        "description": "分组结构：观众信息 / 出票信息 / 偏好，含票种与数量",
        "schema": _form("赛事报名", [
            {"id": "h", "type": "form.heading", "props": {
                "text": "报名参赛/观赛", "level": "h2"}, "style": {}},
            {"id": "s1", "type": "form.section", "props": {
                "title": "1. 联系人信息", "description": "用于接收电子票与通知"},
                "style": {}, "children": [
                    {"id": "f1", "type": "form.text_field", "props": {
                        "label": "姓名", "name": "fullname", "required": True, "width": "half"},
                     "style": {}},
                    {"id": "f2", "type": "form.email_field", "props": {
                        "label": "邮箱", "name": "email", "required": True, "width": "half"},
                     "style": {}},
                    {"id": "f3", "type": "form.phone_field", "props": {
                        "label": "手机号（接收电子票）", "name": "phone", "required": True,
                        "country_code": "UK"}, "style": {}}]},
            {"id": "s2", "type": "form.section", "props": {
                "title": "2. 出票信息", "description": "电子票将发送至上方邮箱"},
                "style": {}, "children": [
                    {"id": "f4", "type": "form.select_field", "props": {
                        "label": "场次", "name": "match_session", "required": True,
                        "options": [{"label": "小组赛 A场 · 6/15", "value": "g1"},
                                    {"label": "1/4 决赛 · 7/2", "value": "qf"}]}, "style": {}},
                    {"id": "f5", "type": "form.select_field", "props": {
                        "label": "票种", "name": "ticket_type", "required": True,
                        "options": [{"label": "标准看台", "value": "standard"},
                                    {"label": "VIP 座席", "value": "vip"},
                                    {"label": "家庭票", "value": "family"}]}, "style": {}},
                    {"id": "f6", "type": "form.number_field", "props": {
                        "label": "人数", "name": "quantity", "required": True, "min": 1,
                        "max": 8}, "style": {}},
                    {"id": "f7", "type": "form.checkbox_field", "props": {
                        "label": "增值服务", "name": "extras", "width": "full", "inline": True,
                        "options": [{"label": "接送服务", "value": "shuttle"},
                                    {"label": "餐食", "value": "catering"},
                                    {"label": "导览讲解", "value": "guide"}]}, "style": {}}]},
            {"id": "s3", "type": "form.section", "props": {"title": "3. 偏好"},
             "style": {}, "children": [
                 {"id": "f8", "type": "form.radio_field", "props": {
                     "label": "通知语言", "name": "language", "required": True, "inline": True,
                     "options": [{"label": "English", "value": "en"},
                                 {"label": "中文", "value": "zh"}]}, "style": {}},
                 {"id": "cs", "type": "form.consent_field", "props": {
                     "label": "我同意活动条款与隐私政策",
                     "policy_url": "https://example.com/privacy", "required": True},
                  "style": {}}]},
            {"id": "sub", "type": "form.submit", "props": {
                "label": "提交报名", "block": True}, "style": {}},
        ], root_props={"layout": "stacked"}),
    },
    {
        "key": "FORM_VOUCHER", "name": "券码兑换/查询表单", "kind": "form",
        "scenario": "promo", "tags": ["券", "兑换", "查询", "优惠", "code", "voucher"],
        "description": "轻量单字段：券码查询 + 邮箱回填",
        "schema": _form("券码兑换", [
            {"id": "h", "type": "form.heading", "props": {
                "text": "输入你的优惠码", "level": "h3", "align": "center"}, "style": {}},
            {"id": "f1", "type": "form.text_field", "props": {
                "label": "优惠码", "name": "voucher_code", "required": True, "width": "full",
                "placeholder": "WATERBOMB20", "max_length": 32}, "style": {}},
            {"id": "f2", "type": "form.email_field", "props": {
                "label": "邮箱（接收结果）", "name": "email", "required": True, "width": "full"},
             "style": {}},
            {"id": "cs", "type": "form.consent_field", "props": {
                "label": "我同意接收本次兑换结果通知", "policy_url": "https://example.com/privacy",
                "required": True}, "style": {}},
            {"id": "sub", "type": "form.submit", "props": {
                "label": "查询优惠码", "block": True}, "style": {}},
        ], root_props={"layout": "stacked"}),
    },
    {
        "key": "FORM_SURVEY", "name": "满意度调研（NPS）", "kind": "form",
        "scenario": "survey", "tags": ["满意度", "调研", "问卷", "nps", "反馈", "survey"],
        "description": "NPS 打分 + 开放建议，含评分语义标签",
        "schema": _form("满意度调研", [
            {"id": "h", "type": "form.heading", "props": {
                "text": "你愿意把我们推荐给朋友吗？", "level": "h3"}, "style": {}},
            {"id": "f1", "type": "form.radio_field", "props": {
                "label": "0=完全不可能，10=极有可能", "name": "nps", "required": True,
                "inline": True, "width": "full",
                "options": [{"label": str(i), "value": str(i)} for i in range(11)]},
             "style": {}},
            {"id": "f2", "type": "form.select_field", "props": {
                "label": "整体满意度", "name": "satisfaction", "required": True,
                "options": [{"label": "非常满意", "value": "5"},
                            {"label": "满意", "value": "4"},
                            {"label": "一般", "value": "3"},
                            {"label": "不满意", "value": "2"},
                            {"label": "非常不满意", "value": "1"}]}, "style": {}},
            {"id": "f3", "type": "form.textarea_field", "props": {
                "label": "还有什么可以改进？", "name": "feedback", "required": False,
                "rows": 4}, "style": {}},
            {"id": "sub", "type": "form.submit", "props": {
                "label": "提交反馈", "block": True}, "style": {}},
        ], root_props={"layout": "stacked"}),
    },
]


# ---------------------------------------------------------------- 落地页模板

def _landing(name: str, sections: list[dict], *, width: str = "1200px") -> dict[str, Any]:
    return {"kind": "landing",
            "root": {"id": "root", "type": "landing.root",
                     "props": {"content_width": width, "bg_color": "#ffffff", "lang": "zh-CN"},
                     "style": {}, "children": sections}}


LANDING_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "CMP_EVENT_LANDING", "name": "赛事营销活动页（完整）", "kind": "landing",
        "scenario": "event",
        "tags": ["赛事", "活动页", "落地页", "售票", "购票", "倒计时", "赛程", "ticket", "match"],
        "description": "旗舰级：导航 + Hero + 数据背书 + 票档 + FAQ + 留资表单 + 页脚",
        "schema": _landing("赛事活动页", [
            {"id": "nav", "type": "landing.nav", "props": {
                "logo_text": "CSTS", "sticky": True,
                "links": [{"label": "赛事亮点", "href": "#highlights"},
                          {"label": "票档", "href": "#tickets"},
                          {"label": "常见问题", "href": "#faq"}]}, "style": {}, "children": []},
            {"id": "hero", "type": "landing.hero", "props": {
                "layout": "centered", "min_height": "620px", "overlay": True,
                "bg_color": "#0b1f3a",
                "bg_image": "https://images.unsplash.com/photo-1522778119026-d647f0596c20?w=1600",
                "pad_top": 96, "pad_bottom": 96}, "style": {},
             "children": [
                 {"id": "cd", "type": "landing.countdown", "props": {
                     "target": "2026-06-15T18:00:00+01:00", "title": "距离开赛"},
                  "style": {}},
                 {"id": "h1", "type": "landing.heading", "props": {
                     "text": "EURO 2028 · 英格兰 vs 法国", "level": "h1", "align": "center",
                     "color": "#ffffff"}, "style": {}},
                 {"id": "p1", "type": "landing.text", "props": {
                     "html": "<p>2026-06-15 19:00 · Wembley Stadium · 官方授权票务</p>",
                     "align": "center", "color": "#e5e7eb", "font_size": "18px"},
                  "style": {}},
                 {"id": "bg", "type": "landing.button_group", "props": {
                     "align": "center", "gap": 12}, "style": {}, "children": [
                     {"id": "b1", "type": "landing.button", "props": {
                         "text": "立即购票", "url": "https://example.com/buy",
                         "variant": "primary", "size": "lg",
                         "utm_params": "utm_source=lp&utm_campaign=event2026"}, "style": {}},
                     {"id": "b2", "type": "landing.button", "props": {
                         "text": "下载行程", "url": "https://example.com/itinerary",
                         "variant": "ghost", "size": "lg"}, "style": {}}]}]},
            {"id": "stats", "type": "landing.section", "props": {"anchor": "highlights",
                                                                "pad_top": 48, "pad_bottom": 48},
             "style": {}, "children": [
                 {"id": "sr", "type": "landing.stat_row", "props": {"items": [
                     {"value": "24", "label": "参赛队"}, {"value": "51", "label": "比赛场次"},
                     {"value": "9", "label": "主办城市"}, {"value": "1.5M+", "label": "现场观众"}]},
                  "style": {}}]},
            {"id": "feat", "type": "landing.section", "props": {"anchor": "features",
                                                                "pad_top": 72, "pad_bottom": 72},
             "style": {}, "children": [
                 {"id": "h2", "type": "landing.heading", "props": {
                     "text": "为什么选择我们", "level": "h2", "align": "center"}, "style": {}},
                 {"id": "fg", "type": "landing.feature_grid", "props": {"columns": 3, "items": [
                     {"icon": "🎫", "title": "官方直连座位图", "desc": "实时库存，锁座 10 分钟"},
                     {"icon": "🚐", "title": "含接送服务", "desc": "伦敦市区酒店往返接送"},
                     {"icon": "🛡️", "title": "官方授权", "desc": "ATOL 受保护，安心出行"},
                     {"icon": "💺", "title": "可选座席", "desc": "从 Economy 到 Hospitality"},
                     {"icon": "📱", "title": "电子票即时送达", "desc": "下单即收，无需纸票"},
                     {"icon": "🌍", "title": "多语言客服", "desc": "中英双语 7×12 小时"}]},
                  "style": {}}]},
            {"id": "tickets", "type": "landing.section", "props": {"anchor": "tickets",
                                                                  "pad_top": 72, "pad_bottom": 72,
                                                                  "bg_color": "#f8fafc"},
             "style": {}, "children": [
                 {"id": "h2b", "type": "landing.heading", "props": {
                     "text": "选择你的票档", "level": "h2", "align": "center"}, "style": {}},
                 {"id": "tc", "type": "landing.ticket_cards", "props": {"layout": "grid",
                 "cards": [
                     {"name": "Economy 看台", "price": "£89", "old_price": "£110",
                      "desc": "Wembley · N/E 区上排", "tag": "热销", "sold_out": False,
                      "url": "https://example.com/buy/econ", "image": ""},
                     {"name": "Club Level", "price": "£189", "old_price": "£240",
                      "desc": "中层视角 · 含餐饮", "tag": "", "sold_out": False,
                      "url": "https://example.com/buy/club", "image": ""},
                     {"name": "Hospitality", "price": "£349", "old_price": "",
                      "desc": "包厢 · 含接送与餐食", "tag": "仅剩 6 席", "sold_out": False,
                      "url": "https://example.com/buy/hosp", "image": ""}]},
                  "style": {}},
                 {"id": "sp", "type": "landing.social_proof", "props": {
                     "rating": 4.8, "count": "2,300+", "source": "Trustpilot",
                     "quote": "2025 年通过 CSTS 看了 5 场比赛，流程顺畅，座席比预期好。"},
                  "style": {}}]},
            {"id": "lead", "type": "landing.section", "props": {"pad_top": 72, "pad_bottom": 72},
             "style": {}, "children": [
                 {"id": "h2c", "type": "landing.heading", "props": {
                     "text": "获取开票提醒", "level": "h2", "align": "center"}, "style": {}},
                 {"id": "fe", "type": "landing.form_embed", "props": {
                     "title": "开票第一时间通知你",
                     "form_id": "FORM_EVENT_REG", "embed_mode": "inline"}, "style": {}}]},
            {"id": "faq", "type": "landing.section", "props": {"anchor": "faq",
                                                               "pad_top": 72, "pad_bottom": 72,
                                                               "bg_color": "#f8fafc"},
             "style": {}, "children": [
                 {"id": "h2d", "type": "landing.heading", "props": {
                     "text": "常见问题", "level": "h2", "align": "center"}, "style": {}},
                 {"id": "fq", "type": "landing.faq", "props": {"default_open_first": True,
                 "items": [
                     {"q": "如何取票？", "a": "下单后 5 分钟内电子票发送至你的邮箱，"
                                            "现场扫码或凭兑换码换取实体票。"},
                     {"q": "可以退票或转让吗？", "a": "赛前 7 天以上可免费退票；"
                                                      "7 天内可免费转让给他人一次。"},
                     {"q": "接送服务包含哪些酒店？", "a": "覆盖伦敦市中心 W1/WC1/EC1/E2 主要酒店，"
                                                      "下单后可在行程单查看接驳点。"},
                     {"q": "支持哪些支付方式？", "a": "Visa / Mastercard / American Express / PayPal，"
                                                  "英镑结算。"},
                     {"q": "如果比赛延期怎么办？", "a": "我们会第一时间通知，并为你自动顺延票务或全额退款。"}]},
                  "style": {}}]},
            {"id": "foot", "type": "landing.footer", "props": {
                "columns": 3, "bg_color": "#0b1f3a", "color": "#c9d1d9",
                "privacy_url": "https://example.com/privacy",
                "terms_url": "https://example.com/terms",
                "legal": "© 2026 Connexus Travel Sports. ATOL 受保护。"},
             "style": {}, "children": [
                 {"id": "sl", "type": "landing.social_links", "props": {"items": [
                     {"name": "Facebook", "url": "https://facebook.com"},
                     {"name": "Instagram", "url": "https://instagram.com"},
                     {"name": "YouTube", "url": "https://youtube.com"}]}, "style": {}}]},
        ]),
    },
    {
        "key": "CMP_PROMO_VOUCHER", "name": "促销券活动页（发券落地）", "kind": "landing",
        "scenario": "promo", "tags": ["促销", "发券", "折扣", "落地页", "券", "voucher", "限时"],
        "description": "强转化券活动页：Hero + 倒计时 + 券码卡 + 条款 + FAQ",
        "schema": _landing("券活动页", [
            {"id": "hero", "type": "landing.hero", "props": {
                "layout": "centered", "min_height": "520px", "bg_color": "#8f0b20",
                "overlay": True, "pad_top": 80, "pad_bottom": 80}, "style": {},
             "children": [
                 {"id": "cd", "type": "landing.countdown", "props": {
                     "target": "2026-12-31T23:59:59Z", "title": "券码失效倒计时"},
                  "style": {}},
                 {"id": "h1", "type": "landing.heading", "props": {
                     "text": "全场 20% OFF", "level": "h1", "align": "center", "color": "#ffffff"},
                  "style": {}},
                 {"id": "p1", "type": "landing.text", "props": {
                     "html": "<p>使用优惠码 <b>WATERBOMB20</b> 立减</p>", "align": "center",
                     "color": "#ffe4e6", "font_size": "20px"}, "style": {}},
                 {"id": "b1", "type": "landing.button", "props": {
                     "text": "立即使用优惠码", "url": "https://example.com/redeem",
                     "variant": "primary", "size": "lg"}, "style": {}}]},
            {"id": "feat", "type": "landing.section", "props": {"pad_top": 64, "pad_bottom": 64},
             "style": {}, "children": [
                 {"id": "fg", "type": "landing.feature_grid", "props": {"columns": 3, "items": [
                     {"icon": "🏆", "title": "全场通票", "desc": "任选一场小组赛"},
                     {"icon": "🎁", "title": "下单加赠", "desc": "满 £200 赠周边"},
                     {"icon": "↩️", "title": "无忧退改", "desc": "赛前 7 天免费退"}]},
                  "style": {}}]},
            {"id": "faq", "type": "landing.section", "props": {"bg_color": "#f8fafc",
                                                               "pad_top": 64, "pad_bottom": 64},
             "style": {}, "children": [
                 {"id": "fq", "type": "landing.faq", "props": {"items": [
                     {"q": "优惠码怎么用？", "a": "结算页输入优惠码即可，每单限用一次。"},
                     {"q": "可以和其他优惠叠加吗？", "a": "不可与会员折扣、团队票叠加。"}]},
                  "style": {}}]},
            {"id": "foot", "type": "landing.footer", "props": {
                "bg_color": "#0b1f3a", "privacy_url": "https://example.com/privacy",
                "legal": "© 2026 Connexus Travel Sports"},
             "style": {}, "children": []},
        ], width="980px"),
    },
    {
        "key": "CMP_LEAD_GEN", "name": "留资/活动报名页", "kind": "landing",
        "scenario": "lead_gen",
        "tags": ["留资", "报名", "活动", "落地页", "表单", "lead", "报名页"],
        "description": "B2B 风格留资页：价值主张 + 表单 + 客户 Logo 墙",
        "schema": _landing("留资页", [
            {"id": "hero", "type": "landing.hero", "props": {
                "layout": "split", "min_height": "520px", "bg_color": "#0f172a",
                "pad_top": 72, "pad_bottom": 72}, "style": {},
             "children": [
                 {"id": "h1", "type": "landing.heading", "props": {
                     "text": "为企业客户提供赛事接待方案", "level": "h1", "color": "#ffffff"},
                  "style": {}},
                 {"id": "p1", "type": "landing.text", "props": {
                     "html": "<p>从票务到接送、餐饮、导览，一站式企业赛事接待，"
                             "支持 20人以上团队。</p>", "color": "#cbd5e1", "font_size": "18px"},
                  "style": {}},
                 {"id": "fe", "type": "landing.form_embed", "props": {
                     "title": "获取企业方案报价", "form_id": "FORM_LEAD_GEN",
                     "embed_mode": "inline"}, "style": {}}]},
            {"id": "stats", "type": "landing.section", "props": {"pad_top": 48, "pad_bottom": 48,
                                                                  "bg_color": "#f8fafc"},
             "style": {}, "children": [
                 {"id": "sr", "type": "landing.stat_row", "props": {"items": [
                     {"value": "320+", "label": "服务企业"}, {"value": "45K", "label": "接待人次"},
                     {"value": "98%", "label": "客户满意度"}, {"value": "12年", "label": "赛事经验"}]},
                  "style": {}}]},
            {"id": "foot", "type": "landing.footer", "props": {
                "bg_color": "#0b1f3a", "privacy_url": "https://example.com/privacy"},
             "style": {}, "children": []},
        ], width="1100px"),
    },
    {
        "key": "CMP_THANKYOU", "name": "转化感谢页（收口页）", "kind": "landing",
        "scenario": "generic",
        "tags": ["感谢", "thank", "完成", "成功", "收口", "确认"],
        "description": "最小可用收口页：确认信息 + 下一步指引 + 客服入口",
        "schema": _landing("感谢页", [
            {"id": "hero", "type": "landing.hero", "props": {
                "layout": "centered", "min_height": "440px", "bg_color": "#0a5f45",
                "pad_top": 72, "pad_bottom": 72}, "style": {},
             "children": [
                 {"id": "h1", "type": "landing.heading", "props": {
                     "text": "✓ 提交成功", "level": "h1", "align": "center", "color": "#ffffff"},
                  "style": {}},
                 {"id": "p1", "type": "landing.text", "props": {
                     "html": "<p>确认邮件已发送至你的邮箱，请查收。<br/>"
                             "我们的团队将在 1 个工作日内与你联系。</p>",
                     "align": "center", "color": "#d1fae5", "font_size": "17px"}, "style": {}},
                 {"id": "bg", "type": "landing.button_group", "props": {"align": "center"},
                  "style": {}, "children": [
                     {"id": "b1", "type": "landing.button", "props": {
                         "text": "返回首页", "url": "https://example.com",
                         "variant": "primary"}, "style": {}},
                     {"id": "b2", "type": "landing.button", "props": {
                         "text": "浏览其他赛事", "url": "https://example.com/events",
                         "variant": "ghost"}, "style": {}}]}]},
            {"id": "foot", "type": "landing.footer", "props": {"bg_color": "#0b1f3a"},
             "style": {}, "children": []},
        ], width="760px"),
    },
    {
        "key": "CMP_SCHEDULE_CHANGE", "name": "赛程变更通知页", "kind": "landing",
        "scenario": "schedule_change", "tags": ["改期", "取消", "变更", "通知", "公告"],
        "description": "变更公告页：新旧对照 + 补救措施 + FAQ + 客服",
        "schema": _landing("赛程变更公告", [
            {"id": "hero", "type": "landing.hero", "props": {
                "layout": "centered", "min_height": "380px", "bg_color": "#7f1d1d",
                "pad_top": 64, "pad_bottom": 64}, "style": {},
             "children": [
                 {"id": "h1", "type": "landing.heading", "props": {
                     "text": "比赛时间变更通知", "level": "h1", "align": "center",
                     "color": "#ffffff"}, "style": {}},
                 {"id": "p1", "type": "landing.text", "props": {
                     "html": "<p>因场馆维护安排，比赛时间由 7/18 15:00 调整为 <b>7/20 19:00</b>。"
                             "您的门票已自动顺延，无需操作。</p>", "align": "center",
                     "color": "#fee2e2"}, "style": {}}]},
            {"id": "info", "type": "landing.section", "props": {"pad_top": 56, "pad_bottom": 56},
             "style": {}, "children": [
                 {"id": "fg", "type": "landing.feature_grid", "props": {"columns": 3, "items": [
                     {"icon": "✅", "title": "门票自动顺延", "desc": "原票号有效，无需换票"},
                     {"icon": "↩️", "title": "可申请退款", "desc": "无法出席可全额退款"},
                     {"icon": "📞", "title": "专线支持", "desc": "020 7946 0000"}]},
                  "style": {}}]},
            {"id": "faq", "type": "landing.section", "props": {"bg_color": "#f8fafc",
                                                               "pad_top": 56, "pad_bottom": 56},
             "style": {}, "children": [
                 {"id": "fq", "type": "landing.faq", "props": {"items": [
                     {"q": "为什么延期？", "a": "场馆临时维护，原定档期不可用。"},
                     {"q": "退款多久到账？", "a": "原路退回，3-5 个工作日。"}]},
                  "style": {}}]},
            {"id": "foot", "type": "landing.footer", "props": {"bg_color": "#0b1f3a"},
             "style": {}, "children": []},
        ], width="880px"),
    },
]


ALL_TEMPLATES = EMAIL_TEMPLATES + FORM_TEMPLATES + LANDING_TEMPLATES