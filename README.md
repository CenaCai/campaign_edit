# Campaign Edit

> 面向**运营 / 前端 / 设计**的内容创作后台。
> 用一句自然语言描述需求 → 系统判断内容类型 → 推荐模板与组件 → 块编辑器精修 → 导出可直接交付的代码或推送到 Mautic。

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)]()
[![Vue](https://img.shields.io/badge/Vue-3.5-42b883)]()
[![License](https://img.shields.io/badge/license-MIT-green)]()

---

## 1. 这套系统解决什么问题

营销内容生产里有三个长期痛点：

|痛点 | 现状 | 本系统的做法 |
|---|---|---|
| 运营不会用设计工具 | 提需求 → 等设计 → 等前端 → 反复改 | **意图识别**：一句话直接生成结构化内容草稿 |
| 三类内容三套技术栈 | 邮件一套模板、表单一套配置、页面一套 builder | **统一 Block Schema**：三类内容共用一份数据契约、一条渲染与导出链路 |
| 编辑器与交付物脱节 | 编辑器里好看，导出后走样 | **预览由后端渲染**：所见即所得，且与导出产物逐字节一致 |

---

## 2.核心架构决策

### 2.1 一份Block Schema 打通全链路

这是整套系统最重要的取舍。三类内容（HTML 邮件 / 表单 / 活动站点）
**不是三个系统**，而是同一份数据结构的三个渲染方言：

```
                      ┌──────────────────────────────┐
  运营自然语言  ──→  │  意图识别                     │
                      │  规则词典 ⊕ LLM + 融合仲裁│
                      └───────────────┬──────────────┘
                                      │ 结构化计划
                      ┌───────────────▼──────────────┐
                      │  模板打分匹配                │
                      │  场景+标签+组件+语言+渠道       │
                      └───────────────┬──────────────┘
                                      │ Block Schema 骨架
   ┌──────────────────────────────────▼──────────────────────────────────┐
   │                    Block Schema（唯一数据契约）                     │
   │  { kind, doc, theme, root: BlockNode[] }│
   └──────────────────────────────────┬──────────────────────────────────┘
         ┌────────────────┬───────────┼───────────┬────────────────┐
         ▼                ▼           ▼           ▼                ▼
    组件注册表 预览渲染      属性面板   lint     导出器Mautic
    （驱动 UI）  （iframe）  （schema 驱动）（可投递性）（4 种目标）（投递）
```

好处是显式的：
- 插件新增一个组件 → 编辑器左栏、属性面板、预览、导出**四件事同时生效**，无需改前端代码
- 新增一种导出目标 → 只写渲染器，不动数据模型
- 意图识别结果（槽位、CTA 文案、主题倾向）可以**直接落到 schema 上**

### 2.2 预览由后端渲染

前端**不复刻**渲染逻辑。iframe 里展示的是后端 `render()` 的真实输出。

如果前端自己渲染，会出现两个必然结果：预览与导出不一致；每次改渲染规则要改两处代码。
对内容系统来说，"导出的东西能直接用"是核心价值，preview 的实现细节不值得为性能牺牲一致性。

代价是每次结构变更有一次 `/preview` 往返 —— 用 400ms 防抖 + 本地乐观更新缓解。

### 2.3 版本只追加，资产不删除

- `content_versions` 只insert，回滚也是追加一条新版本 → 审计链完整
- 内容下线用 `status=archived`，Mautic 侧用 `unpublish` → **没有任何 DELETE 接口**
- 这不是洁癖：内容资产被误删的代价是运营周期重做

---

## 3. 快速开始

### 3.1 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
# macOS / Linux
# .venv/bin/pip install -r requirements.txt

.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```

首次启动会自动完成：建表 → 载入 52 个内置组件 → 16 套内置模板 → 5 套主题 →
3 个项目 → 7 份示例内容 → 安装示例插件。

打开 <http://localhost:8000/docs> 查看 API 文档。

### 3.2 前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://localhost:5173>。Vite 已配好 `/api` 代理到 8000。

### 3.3 演示账号

启动时若检测到未登录，会自动用下列账号静默登录，开箱即用：

| 角色 | 账号 | 密码 |
|---|---|---|
| 管理员 | `admin@csts.dev` | `admin12345` |
| 运营 | `ops@csts.dev` | `ops12345` |
| 设计 | `design@csts.dev` | `design12345` |
| 前端 | `fe@csts.dev` | `fe12345` |

> 生产环境务必改`BOOTSTRAP_ADMIN_PASSWORD` 与 `JWT_SECRET`。

### 3.4 端到端冒烟测试

```bash
cd backend
.venv\Scripts\python -m uvicorn app.main:app --port 8000# 终端 A
.venv\Scripts\python scripts/smoke_test.py                # 终端 B
```

覆盖 74 项断言：鉴权 → 模板 → 意图识别 → 渲染 → 版本/协作/审核 → 导出 → 插件 → MCP。

---

## 4. 意图识别怎么工作

### 4.1 双通道 + 融合仲裁

```
运营输入："7月15日比赛改期提醒邮件，同时做个活动页"
     │
     ├─→ 规则通道（lexicon）        ┐
     │   分层加权：                 │
     │     direct直接点名类型 ×3.0  │  email=8.94
     │     artifact 交付物形态 ×1.5 │  landing=7.40
     │     action   动作动词   ×2.2 │  form=1.97
     │     scenario 营销场景   ×1.6 │  margin=1.54
     │     channel  投放渠道   ×1.4 │  conf=0.66
     │   +否定词窗口检测            │
     │                              ├─→ 仲裁 → 邮件（0.66）
     ├─→ LLM 通道（DeepSeek）      ┘
     │   JSON schema 约束输出
     │   资产拆分 / 依赖关系 / 槽位 / 追问
     │   本地二次校验 + 容错解析
     │
     ▼
 ┌────────────────────────────────────┐
 │ 一致 → 加权融合置信度              │
 │ 不一致 → 取加权高者 × 0.75降置信   │
 │ LLM 不可用 → 纯规则降级（功能完整） │
 └────────────────────────────────────┘
```

规则通道的每个命中都带证据（`rule_evidence`），在界面上完全可见——
运营能看到"因为识别到『改期』和『提醒』，所以判为邮件"。

### 4.2 多意图拆分

一句话要多个交付物时，规则按分隔符切段，LLM 按语义拆 `assets`：

```
"CUP2028 报名页 + 报名表单 + 提醒邮件全套"
  → plan: [landing(primary), form, email]
  → 自动按依赖顺序落地：表单 → 落地页 → 邮件
     （先有表单，落地页才能嵌入）
```

### 4.3 槽位抽取的防编造原则

正则抽出的事实类槽位（日期、价格、折扣、数量）**优先于 LLM 抽取**。
LLM 抽到 `date: "2026-07-15"`，但正则已经抽到了，就用正则的——
避免模型编造日期。

### 4.4 什么时候需要人工确认

`needs_confirm = true` 当任一成立：
- 置信度 < `INTENT_MIN_CONFIDENCE`（默认 0.35）
- 规则与 LLM 判断不一致
- 模板匹配分 < `INTENT_AUTO_TEMPLATE_SCORE`（默认 0.55）
- 存在必填槽位缺失

此时 `auto_create=true` **不会**创建内容，而是在 `explanation.auto_create_blocked` 说明原因。

---

## 5. 渲染与可投递性

### 5.1 邮件（最讲究的部分）

硬约束写在渲染器里，不依赖编辑器自觉：

| 约束 | 原因 |
|---|---|
| table 布局 + inline CSS | Outlook 用 Word 渲染引擎，剥离 `<style>` |
| 禁 position / flex / grid | Outlook 与部分国产客户端不认|
| 禁 CSS 变量 | Gmail 会剥离 |
| 单一 600px 容器 + media query | 移动端不横向滚动 |
| 按钮 VML 兜底 | Outlook 不认 border-radius |
| 所有图片强制 alt | 可访问性 + Gmail 图片策略 |
| 退订链接缺失 = error 级| GDPR / CAN-SPAM 违规风险 |

### 5.2 lint 门禁

`error` 级问题会**阻断保存与导出**（`lint_gate=true` 时）：

```
missing_subject       error   缺少邮件主题
missing_unsubscribe   error   未找到退订链接（合规风险）
css_position          error   position 被 Outlook 忽略
link_js               error   javascript: 链接
no_viewport           error   缺少 viewport meta
no_charset            error   缺少 charset 声明，中文可能乱码
───────────────────────────────────────────
missing_preheader     info    缺少预览文案
no_imageinfo    整封邮件没有任何图片
```

表单检查字段名重复、隐私政策链接、反垃圾机制；落地页检查 `<h1>`、OG meta、CTA、响应式断点、埋点。

---

## 6. 导出目标

| 目标 | 产物 | 适用|
|---|---|---|
| `single_html` | 自包含 HTML | 直接投放、邮件内嵌 |
| `bundle` | zip：`index.html` + `tokens.css` + `schema.json` + `fields.json` + `README.md` | 交接、归档、**可回灌继续编辑** |
| `scaffold` | Vite 工程：`src/styles/` + `src/main.js` + dev/build 脚本 | 交给前端继续开发 |
| `mautic` | POST 到 `/api/emails`、`/api/forms`、`/api/pages` | 直接上线 |

### Mautic 投递已规避的线上坑

来自真实故障复盘，写在 `export/mautic.py` 注释里：

1. **PUT 必须传完整对象** —— Mautic 7 API Platform 对 partial payload 会 500，`update_*` 一律先 GET 全量再合并
2. **部分端点在 `/api/v2`**，已做 fallback
3. **页面跳转靠 `customHtml` 内的 meta-refresh + JS**，`redirectType`/`redirectUrl` 会被构建逻辑忽略
4. **不做 DELETE**，只用 unpublish
5. **表单字段名需避开 Mautic 保留字**，已做重命名并返回 warnings

---

## 7. 插件扩展

一个插件包 = 一个含 `plugin.json` 的目录：

```json
{
  "key": "acme.demo",
  "name": "ACME Demo",
  "version": "0.1.0",
  "kind": "bundle",
  "components": [{
    "key": "acme.banner",
    "name": "ACME 横幅",
    "kind": ["landing", "email"],
    "renderer": "generic_text",
    "props_schema": {
      "text":    { "type": "string", "label": "文案", "default": "Hello ACME", "required": true },
      "color":   { "type": "string", "label": "文字色", "default": "#c8102e" },
      "font_size": { "type": "string", "label": "字号", "default": "28px" }
    },
    "example": { "text": "ACME 官方合作伙伴" }
  }],
  "themes": [{ "key": "acme-brand", "name": "ACME 品牌", "tokens": { "brand": "#0a5" } }],
  "templates": [ /* Block Schema 骨架 */ ],
  "intent_rules": [{ "direct": { "landing": [["acme活动", 2.4]] } }],
  "mcp": { "name": "acme-data", "transport": "stdio", "command": "npx", "args": ["-y", "acme-mcp"] }
}
```

**关键约束：manifest 只声明数据，不允许在插件包里执行任意代码。**
渲染器必须取自宿主白名单。要自定义渲染逻辑，
需在 `backend/app/render/generic.py` 注册并走代码评审。

安装后自动生效：编辑器左栏出现组件、属性面板按 `props_schema` 生成、
导出时正确渲染、意图词典识别新词条。停用后全部回滚。

---

## 8. 目录结构

```
campaign_edit/
├── backend/
│   ├── app/
│   │   ├── config.py           环境变量驱动配置
│   │   ├── db.py 引擎/会话/Base
│   │   ├── deps.py             HS256 JWT + PBKDF2 密码（标准库实现）
│   │   ├── models/             ORM 模型
│   │   ├── schemas/            Pydantic DTO
│   │   ├── blocks/             ★ Block Schema + 组件注册表 + 52 个内置组件
│   │   ├── intent/             ★ 意图识别：lexicon / llm / service 仲裁
│   │   ├── render/             ★ 三类渲染器 + theme token + lint
│   │   ├── export/模板工厂 / 代码导出 / Mautic 投递
│   │   ├── plugins/            manifest / manager / MCP client
│   │   ├── api/v1/             FastAPI 路由
│   │   └── seed/               内置模板 / 主题 / 示例数据
│   ├── scripts/smoke_test.py   74 项端到端断言
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── api/                类型化 API 客户端
│       ├── blocks/schema.ts    ★ 前端 Block Schema 操作（与后端语义一致）
│       ├── stores/             session / editor
│       ├── views/              意图控制台 / 内容库 / 编辑器 / 模板 / 主题 / 插件
│       └── styles/             设计 token + 布局
├── plugins/                    已安装插件（示例：acme.demo）
├── docs/                       详细设计文档
├── deploy/                     Docker Compose / Dockerfile / nginx
└── README.md
```

---

## 9. 常用环境变量

```bash
# 服务
APP_ENV=production
JWT_SECRET=<强随机>
BOOTSTRAP_ADMIN_PASSWORD=<强密码>
AUTH_DISABLED=false
DATABASE_URL=postgresql://user:pass@host:5432/campaign_edit   # 默认 SQLite

# 意图识别 LLM（不配置则跑规则通道，功能完整）
LLM_ENABLED=true
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat
INTENT_MIN_CONFIDENCE=0.35
INTENT_AUTO_TEMPLATE_SCORE=0.55

# Mautic 投递
MAUTIC_API_ENABLED=true
MAUTIC_BASE_URL=https://automarketing.example.com
MAUTIC_USERNAME=xxx
MAUTIC_PASSWORD=xxx

# 插件
PLUGIN_ALLOW_REMOTE_INSTALL=false   # 默认关闭（安全）
PLUGIN_DIR=./plugins
```

---

## 10. 文档

| 文档 | 内容 |
|---|---|
| [`docs/01-architecture.md`](docs/01-architecture.md) | 架构全景、数据流、关键取舍 |
| [`docs/02-intent.md`](docs/02-intent.md) | 意图识别：词典、权重、LLM 协议、融合仲裁 |
| [`docs/03-editor.md`](docs/03-editor.md) | 组件注册、props_schema、主题、编辑器扩展 |
| [`docs/04-data-model.md`](docs/04-data-model.md) | 表结构、版本模型、协作与审核流 |
| [`docs/05-export.md`](docs/05-export.md) | 四种导出目标、Mautic 坑位清单 |
| [`docs/06-extension.md`](docs/06-extension.md) | 插件 manifest、注册流程、MCP 接入 |
| [`docs/07-deploy.md`](docs/07-deploy.md) | 本地/生产部署、备份、迁移 |

---

## 11. 后续方向

1. **视觉回归测试**：渲染产物接入 Playwright 截图，模板改动自动比对
2. **A/B 与变体**：同一内容派生多版本，按分群投放
3. **智能 lint 修复**：lint 问题直接给可一键应用的修复补丁
4. **多租户与品牌隔离**：project 级 token 覆盖已就绪，需补权限模型
5. **Mautic 双向同步**：Mautic 侧改动回流，取代单向投递
6. **素材库联动**：图片/视频从 DAM 拉取，自动裁剪多尺寸

详见 [`docs/08-roadmap.md`](docs/08-roadmap.md)。

---

## License

MIT