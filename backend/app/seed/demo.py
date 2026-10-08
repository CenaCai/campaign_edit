"""示例数据：协作账号、项目、已创建内容。

刻意贴近真实营销团队：一个品牌方项目（CSTS）+ 两个赛事项目（WATERBOMB / EUROCUP），
内容覆盖三种类型与多个状态，便于演示「草稿 → 审核中 → 已通过 → 已发布」全流程。
"""
from __future__ import annotations

DEMO_USERS = [
    {"email": "ops@csts.dev", "name": "运营 ·阿岚", "role": "editor", "password": "ops12345"},
    {"email": "design@csts.dev", "name": "设计 · 谭心", "role": "designer", "password": "design12345"},
    {"email": "fe@csts.dev", "name": "前端 · 小腾", "role": "editor", "password": "fe12345"},
]

DEMO_PROJECTS = [
    {"key": "CSTS", "name": "CSTS 主品牌",
     "description": "Connexus Travel Sports 主站与赛事通票",
     "brand_tokens": {"brand": "#c8102e", "secondary": "#0b1f3a"}},
    {"key": "WATERBOMB", "name": "WATERBOMB 赛事",
     "description": "WATERBOMB 音乐节票务与推广",
     "brand_tokens": {"brand": "#e11d48", "secondary": "#111827"}},
    {"key": "EUROCUP", "name": "EUROCUP 杯赛",
     "description": "欧洲杯赛程与票务营销",
     "brand_tokens": {"brand": "#0057b8", "secondary": "#001f3f"}},
]

# project_key 由 bootstrap 解析成 id；这里用 key 占位
DEMO_CONTENTS = [
    {
        "key": "EM_CUP2028_PROMO_V1", "template_key": "EM_PROMO_VOUCHER",
        "name": "EURO 2028 会员促销发券邮件",
        "locale": "zh-CN", "project_id": None, "status": "draft",
        "note": "含折扣券与倒计时，待设计确认品牌色",
        "doc": {"subject": "会员专享｜新赛季套票 8 折，优惠码 WATERBOMB20",
                "preheader": "限时 7 天，每单满 £100 可叠加使用",
                "description": "CSTS 会员促销 EDM 第一版"},
    },
    {
        "key": "EM_CUP2028_SCHEDULE_V1", "template_key": "EM_SCHEDULE_CHANGE",
        "name": "7月18日赛程改期提醒邮件",
        "locale": "zh-CN", "project_id": None, "status": "in_review",
        "note": "运营已提交，等设计出图；发布前需确认退款政策口径",
        "doc": {"subject": "重要通知｜7月18日比赛时间调整至7月20日 19:00",
                "preheader": "您的门票已自动顺延，无需任何操作",
                "description": "赛程变更高优先级通知"},
    },
    {
        "key": "FORM_CUP2028_REG_V1", "template_key": "FORM_EVENT_REG",
        "name": "EURO 2028 观赛报名表（分组版）",
        "locale": "zh-CN", "project_id": None, "status": "approved",
        "note": "已通过审核，待绑定 Mautic form ID 后发布",
        "doc": {"description": "分组式报名表单，含票种与人数"},
    },
    {
        "key": "FORM_WATERBOMB_LEAD_V1", "template_key": "FORM_LEAD_GEN",
        "name": "WATERBOMB 留资表单（两列）",
        "locale": "zh-CN", "project_id": None, "status": "published",
        "note": "已发布并推送到 Mautic，作为主转化入口",
        "doc": {"description": "标准两列留资表单"},
    },
    {
        "key": "CMP_CUP2028_MAIN_V1", "template_key": "CMP_EVENT_LANDING",
        "name": "EURO 2028 赛事营销活动页",
        "locale": "zh-CN", "project_id": None, "status": "in_review",
        "note": "旗舰页，前端在接入 Analytics；表单位待绑定内容 ID",
        "doc": {"description": "完整赛事活动页：Hero + 票档 + FAQ + 留资"},
    },
    {
        "key": "CMP_WATERBOMB_PROMO_V1", "template_key": "CMP_PROMO_VOUCHER",
        "name": "WATERBOMB 限时优惠活动页",
        "locale": "zh-CN", "project_id": None, "status": "published",
        "note": "已发布，邮件 + 页面双通道推流",
        "doc": {"description": "限时券活动页"},
    },
    {
        "key": "CMP_EUROCUP_THANKS_V1", "template_key": "CMP_THANKYOU",
        "name": "EUROCUP 报名成功收口页",
        "locale": "en-GB", "project_id": None, "status": "published",
        "note": "转化收口页，英文版",
        "doc": {"description": "Thank-you / confirmation page"},
    },
]