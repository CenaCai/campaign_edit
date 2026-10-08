# 扩展机制：插件与 MCP

## 1. 设计立场

**插件包不允许执行任意代码。**

这不是保守，而是因为一旦允许，安装插件包就等于授予代码执行权限。
即使有人工审核，也无法覆盖第三方包被投毒的供应链风险。

因此：
- `plugin.json` 只能**声明数据**（组件定义、主题 token、模板 schema、意图词条、MCP 配置）
- 渲染器必须取自宿主白名单（27 个函数）
- 需要新的渲染逻辑时，在 `backend/app/render/generic.py` 注册并走代码评审
- 远程安装默认关闭（`PLUGIN_ALLOW_REMOTE_INSTALL=false`）

代价是插件作者可能要提 PR，好处是进入代码库的是可审查的代码，
而非运行时加载的黑盒。

---

## 2. 插件包结构

一个插件包 = 一个含 `plugin.json` 的目录（或其zip）。

```
my.plugin/
├── plugin.json        # 必需：声明式定义
├── README.md          # 可选：给人看的说明
└── assets/            # 可选：静态资源
    └── logo.svg
```

### 生成骨架

界面「插件中心」→「生成插件骨架」，或：

```http
GET /api/v1/plugins/scaffold?directory=D:/plugins/my.plugin&key=my.plugin&name=My Plugin
```

会生成一个可运行的示例插件（含 1 组件 + 1 主题 + 1 模板 + 意图规则）。

---

## 3. manifest 规范

### 完整字段

```json
{
  "key": "acme.demo",
  "name": "ACME Demo",
  "version": "0.1.0",
  "kind": "bundle",
  "description": "示例：组件 + 主题 + 模板 + 意图规则",
  "author": "ACME",
  "homepage": "https://acme.example.com",
  "min_app_version": "0.1.0",

  "permissions": [],
  "components": [],
  "themes": [],
  "templates": [],
  "intent_rules": [],
  "mcp": null,
  "assets": []
}
```

### 校验规则（`manifest.py::validate_manifest`）

| 字段 | 规则 |
|---|---|
| `key` | 必须形如 `acme.demo`（带命名空间，避免与内置冲突） |
| `kind` | `component` / `theme` / `template` / `intent_rule` / `mcp` / `bundle` |
| `components[].key` | 必须形如 `csts.ticket_card`（至少两段） |
| `components[].kind` | 必须是 `["email","form","landing"]` 的子集 |
| `components[].renderer` | **必须在白名单内** |
| `templates[].kind` | `email` / `form` / `landing` |
| `intent_rules[]` | 需形如 `{direct: {email: [[词, 权重]]}}` |
| `mcp` | 需含 `command`（stdio）或 `url`（http） |
| manifest 大小 | ≤ 512KB |

单个资源 ≤ 8MB。

---

## 4. 组件（components）

### 定义示例

```json
{
  "components": [{
    "key": "acme.banner",
    "name": "ACME 横幅",
    "kind": ["landing", "email"],
    "category": "hero",
    "container": false,
    "renderer": "generic_text",
    "props_schema": {
      "text":      {"type": "string", "label": "文案", "default": "Hello ACME", "required": true},
      "color":     {"type": "string", "label": "文字色", "default": "#c8102e"},
      "font_size": {"type": "string", "label": "字号", "default": "28px"}
    },
    "style_defaults": {"font-weight": "800"},
    "example": {"text": "ACME 官方合作伙伴"}
  }]
}
```

### 字段说明

| 字段 | 必需 | 说明 |
|---|---|---|
| `key` | ✅ | 带命名空间的唯一标识 |
| `name` | | 左栏显示名 |
| `kind` | ✅ | 可用于哪些内容类型 |
| `category` | | 左栏分组：hero/text/media/action/... |
| `container` | | 是否可容纳子组件 |
| `renderer` | ✅ | 白名单内的渲染函数名 |
| `props_schema` | ✅ | **驱动属性面板**，必须补齐 `label` 与 `default` |
| `style_defaults` | | 样式预填 |
| `children_allowed` | | 容器组件的子组件白名单 |
| `children_limit` | | 子组件数量上限 |
| `example` | | 点击左栏时的初始 props |

### props_schema 支持的控件

| type | 渲染为 | 附加支持 |
|---|---|---|
| `string` | 单行输入 | `editor: "richtext"` → 多行 monospace |
| `number` | 数字输入 | |
| `boolean` | 开关 | |
| `array` | 键值行编辑器（可动态增删） | 元素为 `{key: value}` 对象 |
| `enum` | 下拉 | `enum: ["a","b"]` |

`required: true` 会在 UI 上标红星，并在规范化时填入 default。

### 渲染器白名单

```python
_SAFE_RENDERERS = {
    # 通用（跨类型）
    "generic_section", "generic_spacer", "generic_text", "generic_image",
    "generic_button", "generic_html", "generic_field",
    # 邮件
    "email_section", "email_spacer", "email_text", "email_image",
    "email_button", "email_footer", "email_social",
    # 表单
    "form_field_text", "form_field_email", "form_field_phone",
    "form_field_select", "form_field_number", "form_field_textarea",
    # 落地页
    "landing_section", "landing_text", "landing_image", "landing_button",
    "landing_feature_grid", "landing_spacer", "landing_social_links",
}
```

用 `generic_*` 时由 `render/generic.py::GenericRenderer` 渲染，
会根据组件 `kind` 走对应的 HTML 包装（邮件包`<tr><td>`，落地页直接 `<div>`）。

---

## 5. 主题（themes）

```json
{
  "themes": [{
    "key": "acme-brand",
    "name": "ACME 品牌",
    "kind_scope": "all",
    "tokens": {
      "brand":     "#0a5f45",
      "secondary": "#04120e",
      "radius":    "0",
      "shadow":    "none"
    }
  }]
}
```

安装时会被合并进完整 token 集（未声明的项用默认值补全），
并生成 `css_vars`（`--brand: #0a5f45` 形式）供前端使用。

`kind_scope`：`all` / `email` / `form` / `landing`，
用于按内容类型筛选可用主题。

---

## 6. 模板（templates）

模板就是一份 Block Schema 骨架。

```json
{
  "templates": [{
    "key": "acme_promo_landing",
    "name": "ACME 促销页",
    "kind": "landing",
    "scenario": "promo",
    "locale": "zh-CN",
    "description": "示例：hero + 特性网格 + CTA",
    "tags": ["促销", "acme", "限时"],
    "schema": { /* 完整 Block Schema */ }
  }]
}
```

`tags` 用中文业务词，**是意图匹配的检索入口**（见 `02-intent.md` §5），
不是装饰。标签写得好，运营用自然语言就能匹配到这个模板。

安装时 schema 会被 `validate_schema()` 校验，不合法则整个模板跳过并告警。

---

## 7. 意图规则（intent_rules）

往运行时词典注入词条。

```json
{
  "intent_rules": [{
    "direct":   {"landing": [["acme活动", 2.4], ["acme新品", 2.0]]},
    "scenario": {"promo": ["acme促销"]},
    "action":   {"landing": [["acme预售", 1.0, {"landing": 1.4, "email": 0.6}]]}
  }]
}
```

- `direct`：追加到 `lexicon.DIRECT[kind]`，格式 `[词, 权重]`
- `scenario`：追加到 `lexicon.SCENARIO[场景]`
- `action`：追加到 `lexicon.ACTION`，格式 `[词, 权重, 类型偏置dict]`

安装后运营说「做acme活动页」就能命中landing 类型。

**停用时精确回滚**：`_revoke_intent_rules()` 按「词 + 权重完全匹配」反查移除，
不会误删其他插件或内置的同名词条。

---

## 8. MCP 插件

### 接入外部数据源

MCP（Model Context Protocol）让外部能力接入内容生产链路：
赛事库存、DAM 素材、CRM 数据、多语言翻译。

### manifest 配置

```json
{
  "mcp": {
    "name": "acme-sports-data",
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@acme/mcp-sports"],
    "env": {"ACME_API_KEY": "sk-..."}
  }
}
```

或 HTTP：

```json
{
  "mcp": {
    "name": "acme-remote",
    "transport": "http",
    "url": "http://127.0.0.1:8931/mcp",
    "headers": {"X-Api-Key": "..."}
  }
}
```

### 实现（零 SDK 依赖）

`plugins/mcp_client.py` 用标准库实现 MCP 客户端：

```
stdio:  子进程 + stdin/stdout 上的 JSON-RPC 2.0（行分隔 JSON）
http:   POST JSON-RPC 到 url（Streamable HTTP）
```

支持的协议方法：

| 方法 | 说明 |
|---|---|
| `initialize` | 握手，交换协议版本与能力 |
| `tools/list` | 列出可用工具 |
| `tools/call` | 调用工具 |
| `resources/list` | 列出资源 |
| `prompts/list` | 列出提示词 |

协议版本 `2024-11-05`。

**不实现 sampling 与 roots**（服务端反向调用客户端）——
内容生产场景用不到，实现它们会引入不必要的复杂度与安全面。

### stdio 模式的健壮性

```python
# 服务端可能往 stdout 打日志污染 JSON 流 → 跳过非 JSON 行
while True:
    line = proc.stdout.readline()
    if not line:
        raise MCPClientError(f"MCP 无响应（进程可能退出）: {stderr[:400]}")
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        skipped += 1
        if skipped > 200:
            raise MCPClientError("MCP 输出过多非 JSON 行，已中止")
```

```python
# 进程退出时必须回收，否则会泄漏子进程
finally:
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
```

### 探测与调用

```http
POST /api/v1/plugins/mcp/probe
{ "config": { "command": "npx", "args": ["-y", "@acme/mcp"] } }
```
→ `initialize` + `tools/list`，返回工具清单。

```http
POST /api/v1/plugins/mcp/call
{
  "config": { ... },
  "tool": "get_match_schedule",
  "arguments": { "match_id": "ENG-FRA-2026" },
  "timeout": 30
}
```

安装插件时会自动探测，失败不影响其他扩展的注册（仅记录 `errors`）。

---

## 9. 生命周期

### 安装流程

```
① 校验 manifest（字段、渲染器白名单、大小限制）
② 复制到 plugins/<key>/<version>/
③ upsert plugins 表记录（status=active）
④ 激活：
     ├ components → blocks.registry.register(spec, replace=True)
     ├ themes     → upsert themes 表（补全默认 token）
     ├ templates  → upsert templates 表（validate_schema 校验）
     ├ intent_rules → lexicon 注入
     └ mcp→ MCPClient.probe()
⑤ 记录 registry.applied（注册了什么、哪里失败）
```

安装时 UI 会展示 `plan_install()` 的结果（将要注册什么），确认后才写入。

### 停用（软下线）

```python
def deactivate_plugin(db, plugin):
    for c in plugin.manifest.get("components") or []:
        spec = registry.get(c["key"])
        if spec and spec.get("source_plugin") == plugin.key:
            registry.unregister(c["key"])        # 只移除自己来源的
    _revoke_intent_rules(plugin.manifest, plugin.key)   # 精确反查
    for t in templates where source_plugin == key:
        t.is_active = False
    plugin.status = "disabled"
```

**已用该组件的内容不受影响**：
schema 快照自带 props 与 style，且渲染器是宿主函数。
停用后编辑历史内容会提示组件缺失，但数据不丢。

### 启动同步

```python
def sync_all(db):
    for p in db.query(Plugin).where(Plugin.status == "active"):
        try:
            activate_plugin(db, p)
        except Exception as exc:
            p.status = "broken"
```

进程重启后自动恢复运行时注册。失败的插件标记 `broken` 而非崩溃。

### 扫描

```http
GET /api/v1/plugins/scan
```
扫描 `plugin_dir`，找出已存在但未登记的包、版本差异。UI 上可一键安装。

---

## 10. 安全边界

| 机制 | 说明 |
|---|---|
| **manifest 白名单** | renderer 必须在 `_SAFE_RENDERERS` 内 |
| **key 命名空间** | `acme.*` 格式，避免覆盖内置组件 |
| **无代码执行** | 插件包不含可执行代码 |
| **远程安装默认关闭** | `PLUGIN_ALLOW_REMOTE_INSTALL=false`，需管理员显式开启 |
| **zip-slip 防护** | 解压时校验每个条目路径未逃逸出目标目录 |
| **大小限制** | manifest ≤512KB，单资源 ≤8MB |
| **来源追踪** | 每个注册项记`source_plugin`，停用时只移除自己的 |
| **权限声明** | `permissions` 字段（当前仅记录，不强制） |
| **软卸载** | 默认只 disable，`purge=true` 才删目录 |

---

## 11. 工作流：快速调用组件生成内容

这是扩展机制的最终目的——**让运营不用理解上面任何细节**。

```
1. 设计师/前端开发了一个新组件
        ↓
2. 打包成插件（含 props_schema 与用法文档）
   GET /api/v1/plugins/scaffold?directory=... → 改 plugin.json
        ↓
3. 管理员在插件中心安装（确认注册计划）
        ↓
4. 【运营视角】打开意图控制台，输入
   "做个 ACME 新品首发活动页，要大banner 和立即购买按钮"
        ↓
5. 意图识别命中：
   - LLM 返回 component_hints: ["acme.banner", "button"]
   - 模板打分选中含 acme.banner 的模板
        ↓
6. 一键创建 → 内容已含 ACME banner
        ↓
7. 运营在编辑器左栏直接拖入其它 ACME 组件，属性面板自动出现
        ↓
8. 导出时 acme.banner 由宿主渲染器正确输出为 HTML
```

**运营全程不需要知道什么是 plugin.json。**
组件包是给开发者的，组件面板是给运营的，两者在 props_schema 处汇合。

---

## 12. 开发一个组件的完整流程

### 第1 步：确定渲染器

看你的组件需要什么渲染能力：

| 需求 | 选择 |
|---|---|
| 一段富文本 | `generic_text` |
| 一张图 | `generic_image` |
| 一个按钮 | `generic_button` |
| 一段自定义 HTML | `generic_html` |
| 邮件里的区块 | `email_section` / `email_text` / `email_button` |
| 表单字段 | `form_field_text` / `form_field_email` / ... |
| 页面的区块 | `landing_section` / `landing_feature_grid` / ... |

### 第 2 步：写 manifest

```json
{
  "key": "acme.stat_band",
  "name": "ACME 数据条",
  "version": "0.1.0",
  "kind": "component",
  "components": [{
    "key": "acme.stat_band",
    "name": "ACME 数据条",
    "kind": ["landing"],
    "category": "trust",
    "renderer": "landing_feature_grid",
    "props_schema": {
      "items": {
        "type": "array", "label": "数据项",
        "default": [{"icon": "★", "title": "12年", "desc": "赛事经验"}]
      }
    },
    "example": {"items": [{"icon": "★", "title": "500万", "desc": "服务人次"}]}
  }]
}
```

### 第 3 步：本地安装验证

```http
POST /api/v1/plugins/install
{ "path": "D:/plugins/acme.stat_band" }
```

检查返回：
- `plan.components` 是否包含你的组件
- `applied.components` 是否成功注册
- `applied.errors` 应为空

### 第 4 步：验证全链路

```bash
# 组件是否出现在编辑器左栏
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/blocks?kind=landing" | jq '.[] | select(.key=="acme.stat_band")'

# 组件预览是否正常
curl -X POST http://localhost:8000/api/v1/blocks/preview \
  -H "Content-Type: application/json" \
  -d '{"type":"acme.stat_band","props":{"items":[{"icon":"★","title":"12年","desc":"经验"}]}}'
```

然后在界面上：新建内容 → 拖入组件 → 属性面板确认 → 预览 → 保存 → 导出 bundle，
打开导出的 `index.html` 确认 HTML 正确。

### 第 5 步：注册意图规则（可选）

如果组件对应特定业务词，加上 `intent_rules`，
运营用自然语言就能直接生成含该组件的内容。