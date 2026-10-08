# AI Patch —— 让 AI 修改内容，而不是重建内容

## 1. 这是产品的分界线

从"AI 重建内容"到"AI 改某一处"，是完全不同的两件事：

| | AI 重建 | AI Patch |
|---|---|---|
| 已有的人工编辑 | **全部丢失** | 字节不变 |
| 可逆性 | 不可逆 | 可撤销（版本机制） |
| 可解释 | 只能看整体 | 精确到节点与属性 |
| 验收方式 | 只能人工通读 | 先看 diff 再提交 |

原来的意图识别只能"从零生成"——运营要改一个字，只能自己进编辑器。
加上 Patch 之后，AI 才能成为"操作内容"而不只是"写内容"。

---

## 2. 八种操作

| op | 作用 | 必填字段 |
|---|---|---|
| `set_prop` | 改组件属性 | `target` `prop` `value` |
| `set_style` | 改组件样式 | `target` `style` `value` |
| `set_doc` | 改文档信息 | `field` `value` |
| `set_token` | 改主题 token | `token` `value`（空串=重置） |
| `add_block` | 新增组件 | `type` `props`（可选 `parent_id`） |
| `remove` | 删除组件 | `target` |
| `move` | 移动组件 | `target` `parent_id`（可选 `index`） |
| `set_hidden` | 显示/隐藏 | `target` `hidden` |

示例：

```json
{
  "operations": [
    {"op": "set_prop", "target": "b_a1b2c3", "prop": "text", "value": "立即购票"},
    {"op": "set_style", "target": "b_a1b2c3", "style": "background_color", "value": "#c8102e"},
    {"op": "set_token", "token": "brand", "value": "#0a5f45"},
    {"op": "add_block", "type": "landing.countdown",
     "props": {"target": "2026-06-15T18:00:00+01:00", "title": "距开赛"}},
    {"op": "move", "target": "b_d4e5f6", "parent_id": "b_root", "index": 0}
  ]
}
```

---

## 3. 五条硬约束

### 约束 1：只操作局部，不生成新 schema

所有 handler 都作用于 `copy.deepcopy(schema)` 的副本，
逐条修改。**没有任何一条路径能让模型重写整份文档。**

### 约束 2：每条操作都校验

```
第 3 条操作失败（set_prop）：组件「邮件按钮」没有属性 'colour'；
可用属性：text, url, bg_color, text_color, size, full_width, utm_params…
```

错误信息直接告诉用户怎么改，而不是丢一个 500。

关键校验点：

| 校验 | 拒绝的理由 |
|---|---|
| 节点必须存在 | 防止 AI 幻觉出不存在的 id |
| 属性必须在 `props_schema` 内 | 防止写入无效配置 |
| 样式必须在白名单内（69 个） | 防止写入不可移植 CSS |
| **邮件禁 position/flex/grid** | Outlook 会忽略，布局会错乱 |
| 不能删/移动根节点 | 结构完整性 |
| 不能移动到自己的子节点 | 防循环 |
| `children_allowed` / `children_limit` | 容器约束 |
| 组件类型必须匹配内容类型 | 邮件里不能放表单字段 |
| `set_doc` 长度上限 | subject ≤120 等 |
| `locale` 格式 | 必须 zh-CN / en-GB / en-US |

### 约束 3：先预演再提交

```json
{ "operations": [...], "dry_run": true }
```

返回 `preview_schema` 与 `diff`，不落库。运营看到"将改动 3 处"再决定。

### 约束 4：批量操作原子性

任何一条失败，**整批回滚**。不会出现"前 3 条已生效，第 4 条报错"的中间状态。

已验证：

```http
POST /contents/{id}/patch
{"operations": [
  {"op":"set_prop","target":"btn","prop":"text","value":"不该生效"},
  {"op":"set_prop","target":"不存在","prop":"x","value":"y"}
]}
→ 422，且预览里找不到"不该生效"
```

### 约束 5：走版本机制

Patch 提交后追加新版本，审计链完整。可在版本历史里看到
"Patch 修改 3 处"这条记录，也能一键回滚。

---

## 4. 两条调用路径

### 路径 A：结构化 operations

人和程序都能用：

```http
POST /api/v1/contents/{id}/patch
```

```http
GET  /api/v1/contents/{id}/outline    # 拿组件 id 清单
GET  /api/v1/contents/{id}/ai-suggest  # 拿改进建议（纯规则，永远可用）
```

### 路径 B：自然语言（AI 翻译）

```http
POST /api/v1/contents/{id}/ai-patch
{ "instruction": "把主标题改成「AI 编辑测试」" }
```

返回：

```json
{
  "operations": [{"op":"set_prop","target":"b_x","prop":"text","value":"AI 编辑测试"}],
  "applied": [...],
  "diff": {"summary": {"replace": 1}, "count": 1},
  "preview_schema": {...},
  "message": "AI 生成 1 个操作，将产生 1 处改动。确认后提交 apply_operations。"
}
```

前端展示 diff → 用户确认 → 回传：

```json
{ "apply_operations": [ ... ], "message": "AI 修改（已确认）" }
```

这条路径**不重复调用模型**，直接应用。

### 模型看到的是什么

不是完整 schema，而是：

```
可用的组件类型（add_block 时只能从中选）：
- landing.hero, landing.button, landing.button_group, ...

当前组件清单（target 只能取这些 id）：
- b_h1  [landing.heading]  EURO 2028 赛事营销活动页
- b_p1  [landing.text]  2026-06-15 19:00 · Wembley Stadium
- b_b1  [landing.button] 立即购票  props={"text": "立即购票", "url": "https://..."}
```

给模型清单而不是整份文档，两个原因：
1. token 省一个数量级
2. 模型只能引用真实存在的 id——**在 prompt 层面就抑制幻觉**

---

## 5. LLM 不可用时

`/ai-patch` 返回 503 + 降级指引：

```json
{
  "message": "LLM 未配置，自然语言改写不可用（内容编辑功能完整可用）",
  "fallback": {
    "how": "直接调用 POST /api/v1/contents/{id}/patch 提交 operations",
    "example": {"operations": [
      {"op": "set_prop", "target": "<组件id>", "prop": "text", "value": "新文案"}
    ]},
    "get_outline": "GET /api/v1/contents/{id}/outline 可拿到组件 id 清单"
  }
}
```

**内容编辑功能完全不受影响**——只是不能"用自然语言说"，可以"用 JSON 说"。
`/ai-suggest`（改进建议）是纯规则的，永远可用。

---

## 6. 已验证的行为

```
组件清单可读                      25 个组件
dry_run 预演                      改动 1 处
  └ 预演不落库                    dry_run=true 且无 version 字段
  └ 幂等                          同参数两次预演结果一致
提交 patch 生成新版本              v2
  └ 改动已反映到预览              html 14848 字节
批量操作失败则整体回滚              422
  └ 失败操作未写入任何内容         已回滚
目标不存在被拦截                  422
属性不在白名单被拦                422（提示可用属性列表）
不能删根节点                     422
未知操作被拒                      422
邮件安全样式白名单生效             position 被拒
新增组件                         add:1 reorder:1
跨类型组件被拦                    422（邮件里不能放 form.email_field）
AI 通道无 LLM 时优雅降级           503
改进建议（纯规则）                 正常返回
```

> 关于"幂等"的说明：diff 是相对**当前版本**计算的，
> 所以连续两次相同操作都会报"1 处改动"。
> 要验证的是 `apply_operations` 的确定性——
> 两次预演产出的 schema 逐字节相同，不引入随机 id、不累积副作用。

---

## 7. 配置

```bash
PATCH_ENABLED=true          # 总开关
PATCH_MAX_OPS=40            # 单次结构化操作上限
PATCH_AI_ENABLED=true       # 自然语言改写开关
# LLM 未配置时 AI 路径自动降级，结构化路径不受影响
```

---

## 8. 为什么不给模型完整 schema

这是本设计最重要的一条。三个理由：

1. **模型改写整份 JSON 时极易破坏未涉及的节点** ——
   一次生成 2000 行 JSON，手指抖一下就是人工编辑全丢
2. **无法在提交前告诉用户"将要改什么"** ——
   运营只能"生成 → 全面检查 → 再生成"，体验反而更差
3. **无法保证幂等与可撤销** ——
   同样的指令两次执行结果不同，审计链失去意义

因此：模型看到的是组件清单 + 操作白名单 + 目标类型的 schema，
产出的是一小串 operations；每个 operation 都被逐条校验。

---

## 9. 后续方向

| 方向 | 说明 |
|---|---|
| **多轮对话式编辑** | 保留上下文，支持"再往上移一点""刚才那个按钮" |
| **Patch 建议（预生成）** | 打开内容时后台算好一批可执行建议，运营点选而非打字 |
| **批量 Patch** | 一份模板批量改 20 个活动页的同类问题 |
| **回滚粒度到操作** | 现在回滚到版本，可做到撤销"最近一次 patch" |
| **Patch 模板** | 常用操作序列存为预设："双十一改价三件套" |