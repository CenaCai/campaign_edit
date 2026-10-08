"""意图词典与规则通道。

为什么先做规则：运营话术高度模式化（"发券""改期提醒""留资""倒计时"），
词典命中在真实场景里能覆盖相当比例，且零延迟、零成本、可解释、可回归测试。
规则通道的输出是**加权证据分**，不是结论；结论由 service.py 融合 LLM 后仲裁。

权重分层（乘子，避免拍脑袋）：
  direct      直接点名内容类型   ×3.0
  action      动作/意图动词       ×2.2
  scenario    营销场景           ×1.6
  channel     投放渠道           ×1.4
  artifact    交付物形态         ×1.5
  tone        语气/风格修饰      ×0.8（只微调，不主导）
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------- 词库

# 直接类型信号：命中即强证据
DIRECT: dict[str, list[tuple[str, float]]] = {
    "email": [
        ("邮件", 3.0), ("EMAIL", 3.0), ("email", 3.0), ("edm", 3.0), ("EDM", 3.0),
        ("newsletter", 2.8), ("邮件模板", 3.2), ("邮件营销", 3.2), ("短信", 2.0),
        ("推送邮件", 3.2), ("收件箱", 2.4), ("订阅邮件", 3.0), ("预警邮件", 3.0),
        ("邮件正文", 3.2), ("邮件页", 2.6), ("发送邮件", 3.2), ("群发", 2.6),
    ],
    "form": [
        ("表单", 3.0), ("FORM", 3.0), ("留资", 2.8), ("收集信息", 2.6), ("报名", 2.2),
        ("问卷", 2.8), ("调研", 2.2), ("线索", 2.4), ("线索收集", 3.0), ("注册", 2.0),
        ("订阅", 1.8), ("报名表", 3.0), ("信息收集", 2.8), ("资���", 2.4),
        ("领票信息", 2.6), ("attendee", 2.0), ("lead", 2.0), ("contact form", 3.0),
        ("用户信息", 2.0), ("报名信息", 2.8),
    ],
    "landing": [
        ("落地页", 3.2), ("着陆页", 3.2), ("landing page", 3.2), ("专题页", 2.8),
        ("活动页", 2.8), ("营销活动", 2.6), ("推广页", 2.8), ("投放页", 2.8),
        ("活动站点", 3.0), ("campaign", 2.6), ("站点", 2.2), ("网页", 2.0),
        ("首页", 2.0), ("介绍页", 2.4), ("详情页", 2.4), ("活动官网", 3.0),
        ("赛事页面", 2.8), ("购票页", 2.8), ("售票页", 2.8), ("tracking page", 3.0),
        ("跳转页", 2.6), ("中间页", 2.6), ("报名页", 2.4), ("单页", 2.6),
    ],
}

# 动作动词：体现"要做什么"
ACTION: list[tuple[str, float, dict[str, float]]] = [
    # (词, 权重, 类型偏置)
    ("做", 0.5, {"landing": 1.0, "email": 0.6, "form": 0.5}),
    ("建", 0.5, {"landing": 1.0, "email": 0.6, "form": 0.6}),
    ("创建", 0.6, {"landing": 1.0, "email": 0.7, "form": 0.7}),
    ("生成", 0.6, {"landing": 1.0, "email": 0.8, "form": 0.8}),
    ("设计", 0.7, {"landing": 1.2, "email": 0.9, "form": 0.6}),
    ("写", 0.5, {"email": 1.2, "landing": 0.7, "form": 0.6}),
    ("发", 0.6, {"email": 1.3, "landing": 0.5, "form": 0.4}),
    ("发送", 0.6, {"email": 1.4, "landing": 0.4, "form": 0.3}),
    ("推送", 0.6, {"email": 1.3, "landing": 0.5, "form": 0.4}),
    ("投放", 0.8, {"landing": 1.4, "email": 1.0, "form": 0.8}),
    ("上线", 0.7, {"landing": 1.3, "email": 1.0, "form": 0.6}),
    ("收集", 0.9, {"form": 1.5, "landing": 0.7, "email": 0.4}),
    ("采集", 0.9, {"form": 1.5, "landing": 0.6, "email": 0.4}),
    ("沉淀", 0.8, {"form": 1.2, "email": 0.8, "landing": 0.6}),
    ("转化", 0.7, {"landing": 1.3, "form": 1.1, "email": 0.9}),
    ("改期", 1.0, {"email": 1.4, "landing": 1.1, "form": 0.3}),
    ("提醒", 1.0, {"email": 1.4, "landing": 0.9, "form": 0.3}),
    ("通知", 0.9, {"email": 1.3, "landing": 0.8, "form": 0.3}),
    ("邀请", 0.8, {"email": 1.2, "landing": 1.1, "form": 0.6}),
    ("挽回", 1.0, {"email": 1.5, "landing": 1.0, "form": 0.3}),
    ("促销", 1.0, {"landing": 1.2, "email": 1.3, "form": 0.4}),
    ("发券", 1.2, {"email": 1.5, "landing": 1.2, "form": 0.4}),
    ("拉新", 0.8, {"landing": 1.2, "email": 1.1, "form": 0.9}),
    ("推荐", 0.6, {"email": 1.1, "landing": 1.0, "form": 0.4}),
    ("跟进", 0.7, {"email": 1.3, "landing": 0.9, "form": 0.7}),
]

# 营销场景：决定模板匹配
SCENARIO: dict[str, list[str]] = {
    "promo": ["促销", "发券", "折扣", "特价", "优惠", "秒杀", "限时", "立减", "满减",
              "买二送一", "免费", "赠品", "福利", "补贴", "promo", "sale", "discount", "voucher"],
    "welcome": ["欢迎", "新客", "注册成功", "onboarding", "入会", "新手", "首次", "welcome"],
    "recovery": ["流失", "挽回", "沉睡", "未打开", "未点击", "召回", "唤醒", "re-engage",
                 "inactive", "churn"],
    "abandon": ["弃单", "未支付", "未完成", "弃购", "购物车", "结算中断", "abandon",
                "cart", "checkout"],
    "event": ["赛事", "比赛", "开赛", "开幕", "决赛", "半决赛", "小组赛", "赛程", "球票",
              "门票", "看台", "场馆", "match", "fixture", "event", "ticket", "cup", "final"],
    "schedule_change": ["改期", "延期", "时间变更", "场地变更", "取消", "顺延", "reschedule",
                        "postponed", "cancelled"],
    "announcement": ["公告", "通知", "声明", "通���", "更新", "announcement", "notice"],
    "lead_gen": ["留资", "获客", "线索", "报名", "咨询", "lead", "enquiry", "inquiry",
                 "quote", "预约"],
    "reactivation": ["唤醒", "回访", "召回", "reactivate", "win-back"],
    "newsletter": ["周报", "月报", "资讯", "简报", "newsletter", "digest", "刊期"],
    "verification": ["验证", "验证码", "otp", "确认邮箱", "verify", "verification"],
    "survey": ["满意度", "调研", "问卷", " NPS", "nps", "survey", "feedback"],
}

# 渠道
CHANNEL: dict[str, list[str]] = {
    "email": ["邮件", "edm", "email", "newsletter", "收件箱", "邮件组"],
    "paid_social": ["facebook", "instagram", "meta", "tiktok", "抖音", "小红书", "微信",
                    "朋友圈", "付费", "广告"],
    "ads": ["ads", "google", "投放", "adwords", "ppc", "banner", "联盟"],
    "qr": ["二维码", "qr", "海报", "poster", "物料", "户外"],
    "sms": ["短信", "sms", "whatsapp"],
    "onsite": ["站内", "弹窗", "modal", "首页", "内页"],
    "social": ["社媒", "social", "转发"],
}

# 交付物形态（明确要"代码/文件/站点"的信号 → landing 更重）
ARTIFACT: dict[str, list[tuple[str, float]]] = {
    "landing": [("单页", 1.5), ("站点", 1.4), ("官网", 1.4), ("页面", 1.0),
                ("落地页", 1.6), ("落地", 1.5), ("跳转", 1.2), ("链接页", 1.4),
                ("可以分享", 0.8), ("可分享", 0.8), ("线上访问", 1.0), ("对外", 0.9)],
    "email": [("邮件模板", 1.6), ("邮件版", 1.4), ("edm版", 1.4), ("html邮件", 1.6),
              ("响应式邮件", 1.5)],
    "form": [("表单模板", 1.6), ("字段", 0.8), ("必填项", 1.0), ("校验", 0.9)],
}

# 语气/风格（只做微调）
TONE = ["简洁", "大气", "高级感", "活泼", "科技感", "国际化", "英文", "中文", "双语",
        "紧急", "温和", "直接", " storytelling", "赛博", "极简", "青春"]

# 否定与转折（避免"不要落地页"被误判）
NEGATIONS = ["不要", "不需要", "别做", "不是", "无需", "没有", "不用", "取消", "避免"]

MULTI_DELIMITERS = ["+", "，", ",", "、", "然后", "再", "并且", "同时", "另外", "顺便"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _negated(text: str, kw: str) -> bool:
    """判断关键词前是否有否定词（向前 4 字窗口）。"""
    idx = text.lower().find(kw.lower())
    if idx <= 0:
        return False
    window = text[max(0, idx - 5):idx]
    return any(n in window for n in NEGATIONS)


def score(text: str) -> dict[str, Any]:
    """规则通道：返回各类型加权分、命中证据、槽位线索。"""
    raw = text or ""
    flat = _norm(raw)
    evidence: list[dict] = []
    scores: dict[str, float] = {"email": 0.0, "form": 0.0, "landing": 0.0}
    detail: dict[str, dict] = {"email": {}, "form": {}, "landing": {}}

    def add(kind: str, layer: str, kw: str, weight: float) -> None:
        scores[kind] += weight
        detail[kind][layer] = detail[kind].get(layer, 0.0) + weight
        evidence.append({"layer": layer, "keyword": kw, "kind": kind, "weight": round(weight, 2)})

    # 1) direct
    for kind, kws in DIRECT.items():
        for kw, w in kws:
            if kw.lower() in flat and not _negated(raw, kw):
                add(kind, "direct", kw, w)

    # 2) artifact
    for kind, kws in ARTIFACT.items():
        for kw, w in kws:
            if kw.lower() in flat and not _negated(raw, kw):
                add(kind, "artifact", kw, w)

    # 3) action × kind bias
    for kw, w, bias in ACTION:
        if kw in flat and not _negated(raw, kw):
            for kind, mult in bias.items():
                add(kind, "action", kw, round(w * mult, 2))

    # 4) scenario/channel → 弱偏置（各类型都拿一点，按渠道）
    scenarios = _match_group(SCENARIO, flat)
    channels = _match_group(CHANNEL, flat)
    if scenarios:
        base = 1.6
        add("landing", "scenario", ",".join(scenarios), base)
        add("email", "scenario", ",".join(scenarios), base * 0.9)
        add("form", "scenario", ",".join(scenarios), base * 0.7)
    if channels:
        for ch in channels:
            if ch == "email":
                add("email", "channel", ch, 1.4)
                add("landing", "channel", ch, 0.5)
            elif ch in ("paid_social", "ads", "qr", "sms"):
                add("landing", "channel", ch, 1.4)
                add("email", "channel", ch, 0.6)
            else:
                add("landing", "channel", ch, 0.9)
                add("form", "channel", ch, 0.7)

    # 5) tone（只微调，不改变排序的量级）
    tones = [t for t in TONE if t in flat]
    if tones:
        for k in scores:
            add(k, "tone", ",".join(tones), 0.8)

    # 归一化置信度：sigmoid-ish，除以该类型可达上限的软化值
    top = max(scores.values())
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    margin = top - second
    conf_top = _softmax_conf(scores)
    conf_margin = min(1.0, margin / 4.0)

    return {
        "scores": {k: round(v, 3) for k, v in scores.items()},
        "detail": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in detail.items()},
        "evidence": sorted(evidence, key=lambda e: -e["weight"])[:40],
        "confidence": round(conf_top * 0.7 + conf_margin * 0.3, 4),
        "margin": round(margin, 3),
        "scenarios": scenarios,
        "channels": channels,
        "tones": tones,
        "has_negative": any(n in raw for n in NEGATIONS),
    }


def _softmax_conf(scores: dict[str, float]) -> float:
    if not scores:
        return 0.0
    top = max(scores.values())
    if top <= 0:
        return 0.0
    # top/(sum) 与 top/(top+8) 的折中：既看占比也看绝对强度
    share = top / max(1e-6, sum(scores.values()))
    strength = top / (top + 8.0)
    return max(0.0, min(1.0, 0.5 * share + 0.5 * strength * 2))


def _match_group(group: dict[str, list[str]], flat: str) -> list[str]:
    hits: list[str] = []
    for key, kws in group.items():
        for kw in kws:
            if kw.lower() in flat:
                hits.append(key)
                break
    return hits


# ---------------------------------------------------------------- 槽位抽取

SLOT_PATTERNS: dict[str, str] = {
    # 时间
    "date": r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}日?)|(\d{1,2}月\d{1,2}日)|(\d{1,2}[/-]\d{1,2})",
    "time": r"(\d{1,2}[:：]\d{2})|(\d{1,2}\s?(am|pm|AM|PM))",
    "deadline": r"(\d+\s?(天|小时|周)内)|(\d{4}-\d{2}-\d{2}前)|(截止[到至]?[^，。,\s]{1,12})",
    # 商业
    "discount": r"(\d{1,2}\s?折)|(减\s?\d{1,3})|(立减\s?\d{1,3})|(满\s?\d+\s?减\s?\d+)|(直降\s?\d+)",
    "price": r"[£$€¥￥]\s?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?\s?(?:元|英镑|pound)",
    "coupon": r"(券|优惠券|代金券|兑换码|voucher|coupon|code)",
    "quantity": r"(\d+\s?(张|人|份|套|个|件|票))",
    # 受众
    "audience": r"(老客|新客|会员|球迷|用户|客户|订阅者|潜客| leads?|audience)",
    # 语言
    "language": r"(中文|英文|英式|中英双语|bilingual|EN|EN-GB|中文版|English)",
    # 风格
    "tone": r"(简洁|大气|高级感|活泼|科技感|极简|国际化|双语|青春)",
    # 标识
    "event": r"(EURO\s*2028|世界杯|欧洲杯|UCL|欧冠|赛事|决赛|半决赛|小组赛)",
    "channel": r"(邮件|EDM|短信|SMS|微信|抖音|小红书|Instagram|Facebook|Google)",
}


def extract_slots(text: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    raw = text or ""
    for name, pat in SLOT_PATTERNS.items():
        found = re.findall(pat, raw, flags=re.IGNORECASE)
        vals = []
        for f in found:
            if isinstance(f, tuple):
                v = next((x for x in f if x), "")
            else:
                v = f
            v = v.strip()
            if v and v not in vals:
                vals.append(v)
        if vals:
            slots[name] = vals[:5]
    return slots


def detect_multi_intent(text: str) -> list[dict[str, Any]]:
    """检测一句话里是否包含多个交付物（"做个活动页+表单"）。"""
    raw = (text or "").strip()
    if not raw:
        return []
    parts: list[str] = []
    cur = [raw]
    for d in MULTI_DELIMITERS:
        nxt: list[str] = []
        for seg in cur:
            parts_new = seg.split(d)
            for i, p in enumerate(parts_new):
                if i > 0:
                    nxt.append(p)
                else:
                    nxt.append(p)
        cur = nxt
    segs = [s.strip() for s in cur if s and s.strip()]
    if len(segs) <= 1:
        return []
    out = []
    for seg in segs:
        sc = score(seg)
        top = max(sc["scores"], key=lambda k: sc["scores"][k])
        out.append({"segment": seg, "kind": top if sc["scores"][top] > 0 else None,
                    "scores": sc["scores"]})
    return [o for o in out if o["kind"]]


# 多场景命中时的优先级：越靠前越具体，越优先。
# 例："7月15日比赛改期提醒邮件" 同时命中 event 与 schedule_change，
# 应判为 schedule_change（用户真正想说的是改期，不是赛事内容）。
SCENARIO_PRIORITY: list[str] = [
    "schedule_change", "recovery", "abandon", "verification", "survey",
    "lead_gen", "promo", "welcome", "reactivation", "announcement",
    "newsletter", "event", "generic",
]


def classify_scenario(text: str) -> str:
    """返回单一主场景（多命中时按 SCENARIO_PRIORITY 取最具体者）。"""
    hits = set(_match_group(SCENARIO, _norm(text)))
    if not hits:
        return "generic"
    for k in SCENARIO_PRIORITY:
        if k in hits:
            return k
    return next(iter(hits))