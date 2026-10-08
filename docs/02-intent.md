# 意图识别模块

模块位置：`backend/app/intent/`

```
intent/
├── lexicon.py   规则通道：分层加权词典 + 否定词 + 槽位正则 + 多意图分段
├── llm.py       LLM 通道：JSON schema 约束 + 容错解析 + 无条件降级
└── service.py   融合仲裁：一致/分歧/LLM不可用 + 模板打分 + 追问生成
```

---

## 1. 为什么是双通道

单靠规则：处理不了长句、隐含需求、跨句指代。
单靠 LLM：不可解释、慢、贵，且会**编造事实**（尤其是日期、价格）。

两者互补，且各有一个别的通道无法替代的能力：

|能力 | 规则 | LLM |
|---|---|---|
| 命中哪些词、权重多少 → **可解释** | ✅ | ❌ |
| 零延迟零成本 | ✅ | ❌ |
| 精确抽取日期/价格（不编造） | ✅ 正则 | ⚠️ 会幻觉 |
| 长句与隐含需求 | ❌ | ✅ |
| 拆分多资产及依赖 | ❌ | ✅ |
| 降级可用 | ✅ | ❌ |

融合时**规则抽出的事实类槽位覆盖 LLM**——这是防编造的关键。

---

## 2. 规则通道

### 2.1 分层加权

单一关键词命中不足以判断意图（"活动"在邮件和落地页里都常见）。
因此把词库拆成五层，每层不同量级：

| 层 | 含义 | 乘子 | 示例 |
|---|---|---|---|
| `direct` | 直接点名内容类型 | ×3.0 | 邮件、EDM、表单、落地页、活动站点 |
| `artifact` | 明确要交付物形态 | ×1.5 | 单文件、邮件模板、表单模板、站点 |
| `action` | 动作动词 × 类型偏置 | ×2.2 | 发(邮件×1.4) / 收集(表单×1.5) / 上线(页面×1.3) |
| `scenario` | 营销场景 | ×1.6 | 发券、改期、留资、弃单、NPS |
| `channel` | 投放渠道 | ×1.4 | 邮件 → 邮件×1.4 页面×0.5 |
| `tone` | 语气/风格 | ×0.8 | 简洁、大气、双语（只微调，不主导） |

动作动词带**类型偏置**，避免"发"这个字被平均分配：

```python
("发",   0.6, {"email": 1.4, "landing": 0.5, "form": 0.4}),   # 发 → 强邮件
("收集", 0.9, {"form":   1.5, "landing": 0.7, "email": 0.4}),   # 收集 → 强表单
("上线", 0.7, {"landing":1.3, "email": 1.0, "form": 0.6}),      # 上线 → 强页面
```

### 2.2 否定词窗口

运营会说「**不要**落地页，我要封邮件」。纯关键词匹配会同时命中两者。

```python
def _negated(text: str, kw: str) -> bool:
    idx = text.lower().find(kw.lower())
    window = text[max(0, idx - 5):idx]     # 向前 5 字窗口
    return any(n in window for n in NEGATIONS)   # 不要/不需要/不是/无需/别做/取消/避免
```

### 2.3 场景优先级

一句话可能同时命中多个场景。
「7月15日**比赛改期**提醒邮件」同时命中 `event`（比赛）与 `schedule_change`（改期）——
用户真正想说的是改期，不是赛事内容。

```python
SCENARIO_PRIORITY = [
    "schedule_change",   # 最具体
    "recovery", "abandon", "verification", "survey",
    "lead_gen", "promo", "welcome", "reactivation", "announcement",
    "newsletter", "event",     # 最宽泛
    "generic",
]
```

### 2.4 置信度计算

不是简单的归一化，而是**占比 + 绝对强度**的折中：

```python
share    = top / sum(scores)          # 领先程度
strength = top / (top + 8.0)          # 绝对强度（8 是经验值）
conf_top = 0.5 * share + 0.5 * strength * 2

conf = conf_top * 0.7 + margin_factor * 0.3
# margin_factor = min(1.0, (top - second) / 4.0)
```

`margin` 项很重要：两个类型分差大时，即使绝对分不高，置信度也该高。

实测：

| 输入 | scores | margin | confidence |
|---|---|---|---|
| 给会员发一封促销邮件，发20%折扣券 | email 7.92 / landing 3.60 / form 1.76 | 4.32 | **0.857** |
| 做个欧洲杯活动落地页，要有倒计时和购票按钮 | landing 6.80 / email 0.30 / form 0.25 | 6.50 | **0.945** |
| 这个页面设计得高级一点 | landing 0.84 / email 0.63 / form 0.42 | 0.21 | **0.238**（低于阈值 → 要求人工确认） |

### 2.5 多意图分段

按中文分隔符切段后**逐段独立打分**：

```python
MULTI_DELIMITERS = ["+", "，", ",", "、", "然后", "再", "并且", "同时", "另外", "顺便"]

"CUP2028 报名页 + 报名表单 + 提醒邮件全套"
  → ["CUP2028 报名页", "报名表单", "提醒邮件全套"]
  → [landing, form, email]      ✅ 三种类型全部识别出
```

注意 LLM 通道优先：LLM 能按语义拆分（"…另外还得…"），
规则分词对无显式分隔符的长句无能为力。两者都会给出 `plan`，LLM 优先。

### 2.6 槽位抽取

```python
SLOT_PATTERNS = {
    "date":     r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2}日?)|(\d{1,2}月\d{1,2}日)",
    "discount": r"(\d{1,2}\s?折)|(减\s?\d{1,3})|(满\s?\d+\s?减\s?\d+)",
    "audience": r"(老客|新客|会员|球迷|用户|客户|订阅者|潜客)",
    "coupon":   r"(券|优惠券|代金券|兑换码|voucher|coupon)",
    ...
}
```

正则抽出的**事实类槽位在融合时覆盖 LLM**：

```python
for k, v in rule_slots.items():
    merged[k] = v      # 规则覆盖 LLM，避免编造日期/价格
```

---

## 3. LLM 通道

### 3.1 零 SDK 依赖

用 `urllib` + JSON 直接实现 OpenAI 兼容协议。不引入 `openai` 包的理由：
内容系统不需要流式/工具调用等多模态特性，但需要控制请求超时、重试与降级细节。

### 3.2 System Prompt 锁输出结构

```
你是营销内容创作系统的意图解析器。内容类型只有三种：
- email : HTML 邮件（EDM、通知、促销邮件、欢迎信、改期提醒）
- form  : 表单（留资、报名、信息收集、问卷）
- landing: 着陆页/营销活动站点/落地页/专题页

必须输出 JSON，结构如下：
{
  "primary_kind": "email|form|landing",
  "confidence": 0.0,
  "scenario": "promo|welcome|recovery|abandon|event|schedule_change|...",
  "locale": "zh-CN|en-GB|en-US",
  "assets": [{
    "kind": "...", "role": "primary|supporting",
    "purpose": "这块内容承担什么业务作用",
    "depends_on": [...], "template_hints": [...], "component_hints": [...],
    "content_outline": { "subject": "...", "preheader": "...",
                         "key_messages": [...], "cta": "..." }
  }],
  "slots": {...},
  "followups": [{"slot": "...", "question": "...", "required": true, "options": []}],
  "reasoning": "不超过 80 字的中文判断依据",
  "conflicts": ["意图冲突或缺失信息"]
}

规则：
3. slots 里没有明确给出的，填空字符串，不要编造事实（例如日期、价格）。
4. followups 只放真正影响产出、且原文没给的，最多 3 项。
5. reasoning 必须简洁，禁止复述用户原话。
```

第 3 条是防幻觉的提示词侧配合；即使模型不遵守，第 2.6 节的规则覆盖机制仍会兜底。

### 3.3 三层容错解析

模型不一定听话，所以 `extract_json()` 做三级降级：

```
1. 整段直接 json.loads()
2. 剥离 ```json ... ``` code fence
3. 扫描首个平衡括号（正确跳过字符串内的括号与转义字符）
```

第 3 级实现要点——不能用简单正则找 `{.*}`：
JSON 字符串里可能有 `{` 和 `}`，必须做括号配平 + 字符串态判断。

### 3.4 输出校验与修正

`validate_payload()` 不信任模型输出，逐项校验并修正：

```python
if pk not in VALID_KINDS:
    # 从 assets 推断，再不行兜底 landing
    warns.append(f"primary_kind_invalid:{pk}")

# 保证至少一项资产
if not assets:
    assets = [默认资产]; warns.append("assets_emptied")

# 保证 primary_kind 与 assets 中的 primary 一致
for a in assets:
    if a["kind"] == pk: a["role"] = "primary"

# 置信度钳制到 [0, 1]
conf = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
```

### 3.5 永不向上抛错

```python
try:
    ...
except urllib.error.HTTPError as e:
    return LLMResult(ok=False, error=f"http_{e.code}:{body[:500]}")
except (urllib.error.URLError, TimeoutError, OSError) as e:
    return LLMResult(ok=False, error=f"network:{e}")
except (KeyError, IndexError, ValueError) as e:
    return LLMResult(ok=False, error=f"response_shape:{e}")
```

超时设30s（可配）。超时太长会拖垮接口响应，太短会误杀慢模型。

---

## 4. 融合仲裁

### 4.1 三条路径

```python
if llm_res.ok and rule.kind:
    if llm_res.kind == rule.kind:
        kind = llm_res.kind
        conf = RULE_WEIGHT * rule.confidence + LLM_WEIGHT * llm_res.confidence
        arbiter = "both_agree"
    else:
        # 不一致：取加权高者，并降置信度
        rw = RULE_WEIGHT * rule.confidence
        lw = LLM_WEIGHT * llm_res.confidence
        kind = rule.kind if rw >= lw else llm_res.kind
        conf = max(rw, lw) * 0.75        # ← 分歧惩罚
        arbiter = "rule_wins" / "llm_wins"
        explanation.note = "规则判为 X(0.82)，LLM 判为 Y(0.61)，已按加权取 X 并下调置信度。建议人工确认。"

elif llm_res.ok:
    kind, conf, arbiter = llm_res.kind, llm_res.confidence, "llm_only"

else:
    kind, conf, arbiter = rule.kind, rule.confidence, "rule_only"
    explanation.note = "LLM 不可用（llm_not_configured），已降级为规则通道。建议配置 LLM_API_KEY。"
```

### 4.2 降级不影响功能

LLM 不可用时（未配置 key / 网络故障 / 返回非法 JSON）：

- ✅ 内容类型判断照常工作
- ✅ 模板匹配照常工作
- ✅ 槽位抽取照常工作（规则正则）
- ⚠️ 多意图拆分退化为分隔符分段
- ⚠️ 长句/隐含需求可能误判 → 但`needs_confirm` 会置 true

界面上明确展示 `degraded=true` 与 `llm_error`，
运营知道自己拿到的是降级结果，不会误以为系统"确定"。

### 4.3 何时要求人工确认

```python
needs_confirm = (
    kind is None                                              # 判断不出类型
    or conf < settings.intent_min_confidence                  # 置信度不足 (0.35)
    or (not explanation["agreed"] and llm_res.ok)              # 两通道分歧
    or any(p["template_score"] < settings.intent_auto_template_score for p in plan)  # 模板匹配弱
    or any(any(q["required"] for q in p["followups"]) for p in plan)                  # 必填槽位缺失
)
```

`needs_confirm=true` 时 `auto_create` **不会**创建内容，
只在 `explanation.auto_create_blocked` 说明原因。

---

## 5. 模板打分

```
score = 场景匹配 0.40        # 精确匹配场景 0.40，部分命中 0.15
      + 标签重叠 0.25        # min(1, 命中数/3)
      + 组件命中 0.15        # min(1, 命中数/2)
      + 语言匹配 0.10
      + 渠道匹配 0.10
      + 团队偏好 ≤ 0.05      # log10(usage_count) 加成，用得多说明团队认可
```

标签之所以是"检索入口"而非装饰：模板的 `tags` 用中文业务词
（`["促销", "发券", "折扣", "限时", "倒计时"]`），
直接与运营输入的原文做子串匹配。

场景优先级：**改期 > 挽回 > 促销 > 赛事 > 通用**。
理由同 §2.3——更具体的场景对应更精准的模板。

### 必填追问生成

```python
REQUIRED_SLOTS = {
    "email":   ["audience", "message_goal"],
    "form":    ["audience", "field_set"],
    "landing": ["audience", "cta"],
}
```

LLM 追问的事实类槽位若规则已抽出，直接丢弃（模型常常重复问已知信息）。
再按 `REQUIRED_SLOTS` 补齐缺失的，最多 3 项。

---

## 6. 可解释性

每个命中都带证据，接口完整返回：

```json
{
  "rule_evidence": [
    {"layer": "direct",  "keyword": "促销邮件", "kind": "email",   "weight": 3.20},
    {"layer": "action",  "keyword": "发",       "kind": "email",   "weight": 0.84},
    {"layer": "scenario","keyword": "促销",     "kind": "email",   "weight": 1.44}
  ],
  "explanation": {
    "agreed": false,
    "arbiter": "rule_wins",
    "note": "规则判为 email(0.86)，LLM 判为 landing(0.61)，已按加权取 email 并下调置信度。建议人工确认。",
    "scenarios": ["promo"],
    "channels": ["email"]
  }
}
```

界面上「规则命中证据」面板逐条展示：
运营能看到系统为什么这么判，而不是黑盒出一个结果。

`intents` 表持久化每次识别（含 evidence、scores、耗时），
可通过 `GET /api/v1/intents/history` 与 `GET /api/v1/intents/lexicon` 回溯与调试。

---

## 7. 实测数据

```
输入                                          识别结果          置信度  场景
──────────────────────────────────────────────────────────────────────────
给会员发一封促销邮件，发20%折扣券               email0.857      promo
做个欧洲杯活动落地页，要有倒计时和购票按钮        landing           0.945    generic
做一个留资表单，收集姓名邮箱手机号               form              0.884    lead_gen
7月15日比赛改期提醒邮件，同时做个活动页          email             0.656    schedule_change
CUP2028 报名页 + 报名表单 + 提醒邮件全套         form (3资产)      0.712    event
这个页面设计得高级一点                         landing           0.238    → 人工确认
```

最后一行是有意设计的：分差 0.21、置信度 0.238 远低于阈值，
系统会要求人工确认而不是硬猜。**能说"我不确定"比乱猜更有用。**

---

## 8. 调优建议

| 现象 | 调整方向 |
|---|---|
| 某类内容老是识别错 | 检查该类 `direct` 词库是否覆盖真实运营话术 |
| 置信度普遍偏低 | 调高 `INTENT_RULE_WEIGHT`，或加强 `direct` 词库 |
| 自动创建太保守 | 降 `INTENT_MIN_CONFIDENCE`（但风险上升） |
| 模板匹配不准 | 补模板 `tags`；或调低 `INTENT_AUTO_TEMPLATE_SCORE` |

**先看 `rule_evidence`**：如果系统判错了，证据里一定能看到是哪个词误导了它。
这比直接调权重有效得多。