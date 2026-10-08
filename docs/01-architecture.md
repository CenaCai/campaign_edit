# 架构设计

## 1. 全局视图

```
┌───────────────────────────────────────────────────────────────────────────┐
│                          前端（Vue 3 + Vite + Element Plus）             │
│                                                                           │
│  意图控制台    内容库     编辑器(3栏)    模板中心   主题    插件中心        │
│      │                        │                                          │
│      └────────────────────────┴────��───────────────────────────────────┘│
└───────────────────────────────┬───────────────────────────────────────────┘
                                │ HTTP / JSON（/api/v1）
┌───────────────────────────────▼───────────────────────────────────────────┐
│                          后端（FastAPI + SQLAlchemy 2.0）                │
│                                                                           │
│  api/v1/  ── auth │ intents │ contents │ templates │ themes │ plugins │ system
│       │                                                                   │
│  ┌────┴────────────────────────────────────────────────────────────┐     │
│  │ intent/          意图识别                                         │     │
│  │   lexicon.py       规则通道：分层加权词典 + 槽位正则 + 否定词    │     │
│  │   llm.py           LLM 通道：JSON schema 约束 + 容错解析 + 降级│     │
│  │   service.py       融合仲裁：一致/分歧/LLM 不可用三条路径          │     │
│  └────┬────────────────────────────────────────────────────────────┘     │
│  ┌────▼────────────────────────────────────────────────────────────┐     │
│  │ blocks/           ★ 数据契约层                                   │     │
│  │   schema.py        Block Schema 定义 / 规范化 / 结构化diff│     │
│  │   registry.py      线程安全组件注册表                             │     │
│  │   builtin_*.py     52 个内置组件定义                             │     │
│  └────┬────────────────────────────────────────────────────────────┘     │
│  ┌────▼────────────────────────────────────────────────────────────┐     │
│  │ render/           渲染层                                         │     │
│  │   theme.py24 个 design token → CSS 变量│     │
│  │   email.py         邮件：table布局 + inline CSS + VML + 暗色      │     │
│  │   form.py          表单：语义 HTML + 独立 JS 校验 + 字段清单     │     │
│  │   landing.py       落地页：SSR 语义 HTML + 渐进增强 JS            │     │
│  │   generic.py       插件组件复用的通用渲染器（白名单）│     │
│  │   lint.py          可投递性检查（error 阻断导出）                  │     │
│  └────┬────────────────────────────────────────────────────────────┘     │
│  ┌────▼────────────────────────────────────────────────────────────┐     │
│  │ export/           交付层                                         │     │
│  │   templates.py     模板工厂：schema 实例化 + 槽位落地 + key 生成  │     │
│  │   exporter.py      单文件 HTML / bundle zip / Vite 脚手架│     │
│  │   mautic.py        Mautic 投递（规避 5 类线上坑）                 │     │
│  └────┬────────────────────────────────────────────────────────────┘     │
│  ┌────▼────────────────────────────────────────────────────────────┐     │
│  │ plugins/          扩展层                                         │     │
│  │   manifest.py      插件规范 + 渲染器白名单 + 校验                 │     │
│  │   manager.py       安装/启停/卸载 + 运行时注入与回滚              │     │
│  │   mcp_client.py    MCP 客户端（stdio / Streamable HTTP）           │     │
│  └──────────────────────────────────────────────────────────────────┘     │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   SQLite / PostgreSQL     文件系统              Mautic 7 API
   （内容与版本）      （导出产物 / 插件包）      （投递上线）
```

---

## 2. 关系图：五个核心模块如何协作

需求问的是「意图识别、内容分类、编辑器集成、导出流程之间的关系」。
这是本系统最需要说清楚的部分。

```
                         ┌──────────────────────────┐
                         │运营：一句自然语言         │
                         └────────────┬─────────────┘
                                      ▼
        ┌─────────────────────────────────────────────────────┐
        │ ① 意图识别（intent/）                               │
        │                                                     │
        │输入：raw_text                                      │
        │输出：{ content_type, scenario, confidence,         │
        │        slots, plan[], needs_confirm }│
        │                                                     │
        │  规则 ⊕ LLM 双通道 → 融合仲裁                      │
        │  每个命中都带证据（rule_evidence）→ 可解释          │
        └───────────────────────┬─────────────────────────────┘
                                │ content_type + scenario + slots
                                ▼
        ┌─────────────────────────────────────────────────────┐
        │ ② 内容分类 + 模板匹配                                │
        │                                                     │
        │  内容分类 = 三选一（email / form / landing）          │
        │  模板打分 = 场景 .40 + 标签 .25 + 组件 .15          │
        │           + 语言 .10 + 渠道 .10 + 团队偏好 ≤.05      │
        │                                                     │
        │  输出：Block Schema 骨架（含 doc/theme）             │
        └───────────────────────┬─────────────────────────────┘
                                │ 同一份Block Schema
                                ▼
        ┌─────────────────────────────────────────────────────┐
        │ ③ 编辑器集成（blocks/ + 前端 stores/editor.ts）      │
        │                                                     │
        │  组件面板  ← blocks/registry（后端单一来源）         │
        │  属性面板  ← props_schema（schema 驱动生成表单）│
        │  大纲树    ← schema 树遍历                           │
        │  预览 iframe ← render/（后端渲染，非前端复刻）       │
        │  lint 面板 ← render/lint.py                         │
        │                                                     │
        │  ★ 编辑器从不修改 schema 结构之外的东西              │
        │    → 规范化在保存时于后端统一执行                    │
        └───────────────────────┬─────────────────────────────┘
                                │ 规范化后的 schema（props 白名单 + style 白名单）
                                ▼
        ┌─────────────────────────────────────────────────────┐
        │ ④ 导出流程（export/）                               │
        │                                                     │
        │  lint 门禁 → error 阻断│
        │       │                                                 │
        │       ├─ single_html   自包含 HTML                │
        │       ├─ bundle        zip（可回灌继续编辑）        │
        │       ├─ scaffold      Vite 工程（交给前端）        │
        │       └─ mautic        POST 到 Mautic 上线│
        │                                                     │
        │  四种目标共用同一个 render()，因此产物必然一致      │
        └─────────────────────────────────────────────────────┘
```

### 2.1 关系要点

**意图识别 → 内容分类**：分类结果不是"三选一"的裸字符串，
而是带 `role`（primary/supporting）、`depends_on`（依赖顺序）、`scenario` 的结构化计划。
一句话要多个交付物时，返回的是 `[landing, form, email]` 而不是一个字符串。

**内容分类 → 编辑器**：`kind` 决定了编辑器加载哪个组件集（`/api/v1/blocks?kind=`）、
用哪个 lint 规则集、导出时走哪个渲染器。除此之外三者完全同构。

**编辑器 → 导出**：编辑器只修改 schema，不生成 HTML。
HTML 是导出时刻由后端 `render()` 生成的。
这保证了「编辑器里长什么样」与「导出的就是什么」在实现层面就无法脱节。

**意图槽位 → 内容实体**：`apply_intent_slots()` 会把识别出的
`subject` / `preheader` / `cta` / `tone` 落到 schema 的对应位置。
例如运营说「风格高级一点」，`tone_map` 会把 `radius` 改成 `12px`。

---

## 3. 关键技术取舍

### 3.1 为什么三类内容共用一份Schema

**替代方案**：邮件用 MJML、表单用 JSON Schema、页面用 GrapesJS JSON，
三份数据模型 + 三套渲染器 + 三套导出器。

| 维度 | 三套模型 | 统一Schema（本方案） |
|---|---|---|
| 意图识别落地 | 要为每类各写一套落库逻辑 | 一套，参数化 `kind` |
| 插件新增组件 | 要动三处 | 动一处 |
| 新增导出目标 | 要为三类各写一次 | 写一次，参数化 |
| lint 规则 | 三套规则体系 | 一套，按 kind 分支 |
| 组件注册表 | 三份前端面板 | 一份 |

**代价**：Schema 里存在条件性字段（`doc.subject` 只对 email 有意义）。
这个代价可接受——用 `kind` 判断即可，换来的是上面五项收益。

### 3.2 为什么预览由后端渲染

**替代方案**：前端用 Vue 组件渲染预览。

|问题 | 后果 |
|---|---|
| 邮件渲染逻辑复杂（table 布局、VML 兜底），前端复刻必然走样 | 编辑器里好看，导出后 Outlook 里散架 |
| 同一套渲染规则维护两份 | 改一处忘另一处，bug 必然出现 |
| 前端要引入大量渲染专用依赖 | 包体积膨胀 |

对内容系统而言，「导出的东西能直接投放」是**唯一**的价值标准。
预览慢 200ms 可以接受，产物不可用不可接受。

**代价与缓解**：每次结构变更有一次 `/preview` 往返。
缓解手段：400ms 防抖 + 编辑器本地乐观更新（选中、outline、属性面板不依赖往返）。

### 3.3 为什么插件不允许执行代码

**替代方案**：允许插件包携带 Python 代码，动态 import 渲染器。

**为什么否决**：插件包一旦能执行代码，安装它就等于授予任意代码执行权限。
即使有"审核"，也无法覆盖第三方包被投毒的供应链风险。

**本方案**：manifest 只能声明数据（组件定义、主题 token、模板 schema、意图词条）。
自定义渲染逻辑需在宿主 `render/generic.py` 注册并走代码评审——
成本是插件作者要提 PR，好处是进入代码库的是可审查的代码而非运行时加载的黑盒。

**渲染器白名单**（`manifest.py::_SAFE_RENDERERS`）：
插件可复用的 27 个渲染函数，覆盖通用区块与三类内容的基础组件。

### 3.4 为什么版本只追加

回滚如果直接改历史版本，审计链就断了——出问题时无法回答
「上周五发的邮件，当时是谁改的、改了什么」。

本方案回滚 = 用目标版本的内容创建新版本：
`v1 → v2 → v3(回滚自v1)`，v1/v2/v3 全部保留，diff 链完整。

### 3.5 为什么下线不用删除

内容资产误删的代价是整个运营周期重做，且往往无法恢复。
因此系统中**没有任何 DELETE 内容资产的接口**：

- 内容下线 → `status=archived`
- Mautic 下线 → `PUT /api/emails/{id}/unpublish`（`isPublished=false`）
- 插件卸载 → 软卸载（停用 + 移除运行时注册），`purge=true` 才删目录

---

## 4. 数据流：一次完整的内容生产

以运营输入
> 「做个欧洲杯活动落地页，要有倒计时和购票按钮，再配一个留资表单收集邮箱」

为例：

```
① POST /api/v1/intents
   text="做个欧洲杯活动落地页…"
   ↓ 规则命中：落地页(direct 3.2) + 留资表单(3.0) + 站点(2.2)
     → scores: landing=6.80, form=3.15, email=0.30
   ↓ LLM（若配置）拆分 assets: [landing(primary), form(supporting)]
   ↓ 仲裁：一致 → 置信度 0.95
   ↓ 槽位抽取：event=["欧洲杯"], component_hints=["countDown","ticketCard"]
   ↓ 模板打分：CMP_EVENT_LANDING=0.82, FORM_LEAD_GEN=0.71
   ↓ 追问：form 缺 field_set / landing 缺 cta → needs_confirm=true
   ↓ 写入 intents 表（含 rule_evidence，便于回溯）
   ←返回：引擎=hybrid, content_type=landing, confidence=0.95, plan[2]

② POST /api/v1/intents { auto_create: true }
   needs_confirm=true → 拒绝自动创建，返回 auto_create_blocked
   ↓ 运营回答追问后重试（或选模板）
   ↓ 按依赖顺序落地：form → landing
       form:instantiate(FORM_LEAD_GEN) → apply_intent_slots → create_content
       landing: instantiate(CMP_EVENT_LANDING)
               → apply_intent_slots（CTA 写入第一个按钮）
               → form_embed.form_id 指向刚创建的表单
   ←返回：created_contents[2]

③ 打开编辑器
   GET /api/v1/blocks?kind=landing   → 20 个 landing 组件（含插件组件）
   GET /api/v1/contents/{id}/schema → Block Schema
   GET /api/v1/contents/{id}/preview→ { html, lint, info }
   ↓ 前端按 props_schema 生成属性面板；iframe 展示后端渲染的 HTML

④ 编辑 + 保存
   POST /api/v1/contents/{id}/save { schema, lint_gate: true }
   ↓ normalize_schema：剔除未声明 props、过滤 style 白名单
   ↓ lint：error 级阻断（有则返回 422 +完整 lint 结果）
   ↓ 追加 content_versions 记录 + 计算 schema 级 diff
   ↓ lock_version += 1（乐观锁）

⑤ 导出
   POST /api/v1/contents/{id}/export { target: "bundle" }
   ↓ lint 门禁再检一次
   ↓ render() → index.html
   ↓ tokens_to_css() → tokens.css
   ↓ schema 原样 → schema.json（可回灌）
   ↓ README.md（含 token 表 + 交接说明）
   ↓ zip 打包
   ←返回：zip 路径 + lint 摘要
```

---

## 5. 并发与一致性

### 5.1 乐观锁（防覆盖写）

```
contents.lock_version 每次保存 +1
前端保存时回传自己的 lock_version
   ├─ 一致 → 保存，lock_version += 1
   └─ 不一致 → 409 + 当前 lock_version
```

适用场景：两人同时打开同一内容，A 改完保存后 B 再保存会被拦截，
并收到「内容已被他人更新」的明确提示。

### 5.2 草稿锁（软独占 +TTL）

```
POST /contents/{id}/lock { action: "acquire", ttl_seconds: 300 }
   ├─ 无锁 或 锁已过期 或 锁属于自己 → 获得锁，设 lock_expires_at
   └─ 锁有效且属于他人 → 409 + 锁持有者 + 过期时间

前端每 90s 发 heartbeat 续期
```

用TTL 而非强锁：进程崩溃不会留下永久死锁。

### 5.3 审核状态机

```
draft ──→ in_review ──→ approved ──→ published
  │           │  │          │  │
  │           ↓  ↓          ↓  ↓
  └───────→ archived ←───────┴──┘
            │
            └──→ draft（回退，允许改）

非法迁移返回 409 + 当前状态允许的迁移列表
```

`ContentStatus.TRANSITIONS` 定义边；`services.transition()` 校验。
发布需要 `admin` 或 `editor` 角色。

---

## 6. 可扩展性边界

**当前刻意不做**（留给后续版本）：

| 项 | 原因 |
|---|---|
| 实时协同编辑（CRDT/OT） | 与"版本只追加"的审计模型冲突，需要重新设计版本语义 |
| 内容资产 DELETE | 见3.4 |
| 插件执行代码 | 见 3.3 |
| 前端渲染预览 | 见 3.2 |

**这些边界是有意的**。每一条都是为了保证「导出的东西能直接用」和「资产不会丢」这两条底线。
扩展方向见 `08-roadmap.md`。