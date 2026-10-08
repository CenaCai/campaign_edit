# 模板与编辑器

## 1. Block Schema：全链路唯一数据契约

三类内容共用一份数据结构。位置：`backend/app/blocks/schema.py`。

```json
{
  "schema_version": "1.0",
  "kind": "email | form | landing",
  "doc": {
    "key": "EM_CUP2028_PROMO_V1",
    "name": "EURO 2028 会员促销邮件",
    "locale": "zh-CN",
    "subject": "会员专享｜20% OFF",
    "preheader": "限时 7 天，每单满 £100 可叠加",
    "description": "CSTS 会员促销 EDM 第一版"
  },
  "theme": {
    "theme_id": "csts-dark-brand",
    "token_overrides": { "brand": "#c8102e" }
  },
  "root": {
    "id": "root",
    "type": "email.root",
    "props": { "width": "600px", "bg_color": "#f4f5f7", "align": "center" },
    "style": {},
    "children": [ /* BlockNode */ ]
  }
}
```

### BlockNode

```json
{
  "id": "b_a1b2c3d4e5",         // 全局唯一且稳定（评论锚点/协作/埋点依赖）
  "type": "email.button",       // 组件 key
  "props": { "text": "立即购票", "url": "https://...", "size": "lg" },
  "style": { "padding": "16px" },
  "children": [],               // 仅容器组件有
  "hidden": false,// 可临时隐藏，不删除
  "behaviors": { }              // 预留：条件显示规则
}
```

### 三条不变量

写入时由 `normalize_schema()` 强制执行，不是"建议"：

1. **props 白名单**：只允许组件 `props_schema` 声明过的字段，
   未声明的键在保存时被剔除。这样插件不会污染内容数据。
2. **style 白名单**：只允许 `ALLOWED_STYLE_KEYS`（69 个可移植 CSS 属性）。
   email 模式额外剔除 `position/top/left/gap/flex_*/box_shadow` 等 Outlook 不认的属性。
3. **id 稳定**：模板实例化时用 `_reid()` 重新生成全部节点 id，
   因此多份内容不会共享锚点——评论、埋点、A/B 实验互不干扰。

---

## 2. 组件注册表

位置：`backend/app/blocks/registry.py`。线程安全（`threading.RLock`），
因为插件安装会在运行时注入。

### 组件定义（BlockSpec）

```python
{
  "key": "email.product_card",
  "name": "商品/服务卡",
  "kind": ["email"],                    # 可用于哪些内容类型
  "category": "commerce",               # 左栏分组
  "container": False,
  "renderer": "email_product_card",     # 渲染函数名（见 §5 白名单）
  "props_schema": {
    "title":     {"type": "string", "label": "标题", "default": "服务名称", "required": True},
    "price":     {"type": "string", "label": "价格", "default": "£0"},
    "old_price": {"type": "string", "label": "划线价", "default": ""},
    "badge":     {"type": "string", "label": "角标", "default": ""},
    "align":     {"type": "string", "label": "对齐",
                  "enum": ["left", "center"], "default": "left"},
  },
  "style_defaults": {"padding": "16px"},
  "children_allowed": None,             # 容器组件才需要
  "children_limit": {"max": 6},
}
```

### props_schema 驱动的属性面板

**这是本系统省前端代码的关键**。属性面板不硬编码任何字段：

```vue
<!-- EditorView.vue：按 props_schema 类型自动选择控件 -->
<el-select      v-if="p.meta.enum" />       <!-- enum → 下拉 -->
<el-switch      v-else-if="type==='boolean'" />
<el-input-number v-else-if="type==='number'" />
<div            v-else-if="type==='array'" /> <!-- array → 键值行编辑 -->
<el-input type="textarea" v-else-if="editor==='richtext'" />
<el-input       v-else />
```

因此插件新增组件时：
**只写 manifest → 左栏出现 → 属性面板自动生成 → 预览正常 → 导出正常**，
前端一行代码都不用改。

### 内置组件清单（52 个）

| 类型 | 数量 | 组件 |
|---|---|---|
| `email` | 16 | root / header / hero / text / heading / image / button / button_group / columns / column / divider / spacer / product_card / ticket_card / countdown / social / footer |
| `form` | 15 | root / section / heading / text_field / email_field / phone_field / number_field / select_field / radio_field / checkbox_field / textarea_field / date_field / hidden_field / consent_field / submit / captcha |
| `landing` | 20 | root / nav / hero / section / heading / text / image / video / button / button_group / countdown / feature_grid / stat_row / social_proof / ticket_cards / faq / map / form_embed / spacer / footer / social_links |

组件定义分别在 `builtin_email.py` / `builtin_form.py` / `builtin_landing.py`。

### 容器约束

```python
"email.columns": {
    "container": True,
    "children_allowed": ["email.column"],
    "children_limit": {"max": 3},
}
```

编辑器拖入组件时先检查 `children_allowed`，
不合规则给出明确提示而不是静默失败：

> 「邮件多列布局」只允许放入：email.column

---

## 3. 主题与设计 token

位置：`backend/app/render/theme.py`。**24 个 token**，一份定义驱动三处：
编辑器预览、导出产物、Mautic 主题。

### Token 清单

| 类别 | Token |
|---|---|
| 品牌色 | `brand` `brand_dark` `brand_light` `secondary` `accent` |
| 语义色 | `success` `warning` `danger` |
| 文字 | `text` `text_muted` `text_inverse` |
| 背景/描边 | `bg` `bg_subtle` `border` |
| 圆角 | `radius` `radius_pill` |
| 间距/字号 | `space_unit` `font_size_base` `line_height` |
| 字体 | `font_family` |
| 阴影 | `shadow` `shadow_lg` |
| 尺寸 | `email_width`（600px）`container_width`（1200px） |

### 三层覆盖优先级

```
schema.theme.token_overrides   （内容级，最高）
  ↓
theme.tokens                  （项目/主题级）
  ↓
TOKEN_META 默认值              （系统级）
```

意图识别识别到"风格高级一点"时，`apply_intent_slots()` 会写：
```python
tone_map["高级感"] = {"radius": "12px", "brand_light": "#f3f0ea"}
```
也就是说**意图直接影响了主题**，这是统一 Schema 带来的直接收益。

### 输出 CSS

```css
/* design tokens —— 由 Campaign Edit 主题系统生成，请勿手改 */
:root {
  --brand: #c8102e; /* 品牌主色（CTA/强调） */
  --brand_dark: #8f0b20; /* 品牌深色（hover/页脚底） */
  ...
}
```

导出的每个 bundle 都含完整 `tokens.css`。
交接给前端时替换该文件即可整站换肤，不需要改组件。

### 内置主题（5 套）

`csts-dark-brand`（品牌默认）/ `csts-light-modern` / `football-vivid` /
`email-safe-flat`（邮件专用：圆角 0、无阴影）/ 以及插件提供的主题。

---

## 4. 编辑器架构

### 三栏布局

```
┌──────────────┬────────────────────────────────┬────────────────┐
│ 左栏264px    │ 中栏 flex                       │ 右栏 340px     │
│              │                                 │                │
│ [组件][大纲] │ 工具条：状态流转/版本/导出/保存 │ [属性][样式]   │
│              │ lint 汇总条                     │ [文档][评论]   │
│ 按分类分组   │─────────────────────────────────│                │
│ 搜索过滤     │ 预览舞台                        │ 属性：schema驱动│
│ 拖拽/点击    │┌───────────────────────────┐   │ 样式：token 覆盖│
│              │ │ iframe(srcdoc=后端渲染)  │   │ 文档：subject 等│
│ 大纲树       │ │ 桌面/平板/手机 三档宽度  │   │ 评论：区块锚定 │
│ 缩进显示     │ └───────────────────────────┘   │ 版本：历史+回滚│
└──────────────┴─────────────────────────────────┴────────────────┘
```

### 预览：后端渲染 + iframe

```ts
// EditorView.vue
<iframe :srcdoc="ed.previewHtml" sandbox="allow-same-origin allow-scripts" />
```

`ed.previewHtml` 来自 `GET /api/v1/contents/{id}/preview`，
即后端 `render()` 的真实输出。

**为什么不用前端渲染**：见 `01-architecture.md` §3.2。
预览与导出走同一个 `render()`，实现层面就无法脱节。

### 预览内的选中与悬停

后端渲染的是纯 HTML（无交互），因此选中态由前端注入：

```ts
function injectSelectionBridge() {
  // 1. 注入样式：[data-ce-node]:hover { outline-color: #c8102e }
  // 2. 按 DOM 深度优先顺序与 schema 节点顺序对齐，标注 data-ce-node="<id>"
  // 3. 绑定 click → selectedId；mouseover → hoveredId
  // 4. 点击时显示节点类型徽标
}
```

DOM 顺序对齐依赖渲染器保持 `children` 顺序——
这是渲染器的一个隐式契约，若重写渲染器需注意。

### 状态管理（Pinia）

`stores/editor.ts` 承担：
- schema 本地副本（编辑所见即所得）
- 60 步撤销/重做栈（Ctrl+Z / Ctrl+Shift+Z）
- 400ms 防抖的预览刷新
- 草稿锁心跳（90s）
- 协作评论与审核记录
- `props_schema → 控件` 的映射元数据

---

## 5. 渲染器

### 5.1 邮件渲染器（`render/email.py`）

最讲究的部分。硬约束写在代码里，不依赖编辑器自觉：

| 约束 | 实现方式 |
|---|---|
| table 布局 | 所有块渲染为 `<table role="presentation">` |
| inline CSS | `style_str()` 序列化为内联样式 |
| 禁现代布局 | `EMAIL_UNSAFE_STYLE_KEYS` 在 normalize 阶段剔除 |
| 移动端 | `<style>` 里单一 media query + `.ce-pad/.ce-stack` 类 |
| Outlook 按钮 | `<!--[if mso]><v:roundrect>` VML 兜底 |
| 暗色模式 | `prefers-color-scheme` 补丁 |
| 多列 | `<td width="33%">` + `.ce-hide-mobile` 移动端堆叠 |
| 安全清洗 | `_sanitize_inline_html()` 剥离 script/事件属性/CSS 表达式 |
| URL 净化 | `_sanitize_url()` 拦 `javascript:`/`data:`，相对路径补 https |

输出结构：

```html
<!DOCTYPE html><html><head><meta charset><style>/* 仅响应式与暗色 */</style></head>
<body>
  <div style="display:none...">预注文案{{ filler }}</div>
  <table width="100%" style="background:#f4f5f7;padding:24px 8px">
    <tr><td align="center">
      <table style="max-width:600px">... 内容行 ...</table>
    </td></tr>
  </table>
</body></html>
```

### 5.2 表单渲染器（`render/form.py`）

产物是三件套：

1. **语义 HTML**：`<label for>` / `aria-required` / `<fieldset>` / `role="alert"`
2. **独立 JS**（零依赖，约 200 行）：校验 + AJAX 提交 + UTM 透传 + 埋点
3. **字段清单** `fields.json`：供 CRM / Mautic / 数据层消费

字段模型（编辑器、校验、Mautic 映射三处共用）：

```json
{
  "name": "phone", "label": "手机号", "input_type": "tel",
  "required": true, "width": "half",
  "rules": {"required": true, "pattern": "^\\+?44?\\s?\\d{9,10}$", "phoneCountry": "UK"},
  "mautic_field": "phone", "consent": false
}
```

校验规则从 props 推导：`required` / `pattern` / `min`/`max` /
`minLength`/`maxLength` / `type=email` / 按 `country_code` 的手机号正则。

反垃圾：默认 `honeypot`（隐藏字段 `ce_website`），
可切 `recaptcha_v3` / `turnstile`。

UTM 透传：渲染 `[data-ce-utm]` 隐藏域，JS 从 URL query 读取回填。

### 5.3 落地页渲染器（`render/landing.py`）

**SSR 直出**：无 JS 也能读全文与所有 CTA。
JS 只做增强：倒计时、FAQ 折叠、弹层表单、CTA 埋点。

关键设计：
- 区块语义化标签（`<section>` / `<nav>` / `<figure>` / `<details>`）
- 响应式用 `clamp()` 与 `auto-fit` 网格，无硬编码断点
- 表单嵌入支持 inline / modal / drawer 三种模式
- FAQ 用原生 `<details>`，无 JS 也能展开
- 埋点：`data-track="cta"` + `dataLayer.push`

### 5.4 通用渲染器（`render/generic.py`）

给插件组件复用。27 个渲染函数在白名单内，插件声明 `renderer` 即可。

```python
_SAFE_RENDERERS = {
    "generic_section", "generic_spacer", "generic_text", "generic_image",
    "generic_button", "generic_html", "generic_field",
    "email_section", "email_spacer", "email_text", "email_image", "email_button",
    "email_footer", "email_social",
    "form_field_text", "form_field_email", "form_field_phone", "form_field_select",
    "form_field_number", "form_field_textarea",
    "landing_section", "landing_text", "landing_image", "landing_button",
    "landing_feature_grid", "landing_spacer", "landing_social_links",
}
```

---

## 6. 扩展编辑器

### 加一个内置组件

1. 在 `builtin_*.py` 里加 `BlockSpec`（含完整 `props_schema` 与 label）
2. 在对应渲染器加 `r_<type_underscored>` 方法
3. `load_builtins()` 自动注册（幂等）

前端**零改动**。

### 加一个插件组件

1. 写 `plugin.json`，声明 `components[].key` / `kind` / `renderer` / `props_schema`
2. `renderer` 取白名单值（如 `generic_text`）
3. 安装插件

同样前端零改动。详见 `06-extension.md`。

### 换整套视觉

改主题 token，不动组件：

```json
{ "key": "my-brand", "tokens": { "brand": "#0a5f45", "secondary": "#04120e",
                                "radius": "0", "shadow": "none" } }
```

所有引用该 token 的内容同步变化，且历史内容也变——
这是"主题在内容之上"的设计意图。

---

## 7. 可投递性检查（lint）

位置：`render/lint.py`。**error 级问题会阻断保存与导出**。

### 邮件规则（基于真实送达事故清单）

| 代码 | 级别 | 说明 |
|---|---|---|
| `missing_subject` | error | 缺少邮件主题 |
| `missing_unsubscribe` | error | 无退订链接（GDPR / CAN-SPAM 违规风险） |
| `css_position` | error | position 被 Outlook 忽略 |
| `css_flex` / `css_grid` | error | Outlook 与部分国产客户端不支持 |
| `css_var` | error | Gmail 会剥离 CSS 变量 |
| `css_import` / `css_backdrop` / `css_sticky` | error | 客户端不支持 |
| `link_js` | error | `javascript:` 链接 |
| `no_viewport` | error | 移动端会按 980px 缩放 |
| `no_charset` | error | 中文可能乱码 |
| `subject_too_long` | warn | >60 字符，移动端截断 |
| `img_no_alt` | warn | 无障碍 + Gmail 图片策略 |
| `link_relative` | warn | 邮件必须用绝对 URL |
| `no_media_query` | warn | 缺移动端适配 |
| `width_too_wide` | warn | >640px 会横向滚动 |
| `placeholder_left` | warn | 仍有「在此输入内容」占位 |
| `missing_preheader` | info | 客户端会抓正文首句 |
| `no_image` | info | 整封无图 |

### 表单规则

`duplicate_field`（error，字段名重复）/ `no_label`（error，无障碍）/
`no_privacy_link`（warn，GDPR）/ `no_antispam`（info，建议 honeypot）

### 落地页规则

`no_title`（error）/ `not_responsive`（error）/ `no_h1`（warn）/
`no_seo_meta`（warn，OG 与 viewport）/ `no_cta`（warn）/ `no_tracking`（info）

### 评分

```python
score = 100 - error*20 - warn*5 - info*1
```

在界面上以"可投递性 XX 分 · N error"展示，颜色分级。
error 存在时导出按钮直接失败，并返回完整 lint 结果。