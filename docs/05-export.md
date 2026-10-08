# 代码导出与交付

## 1. 四种导出目标

统一入口：

```http
POST /api/v1/contents/{id}/export
{
  "target": "single_html | bundle | scaffold | mautic",
  "version_id": "可选，缺省用当前版本",
  "publish": false,
  "update_mautic": false,
  "redirect_url": "",
  "allow_lint_error": false
}
```

四种目标共用同一个 `render()`，因此**产物必然与编辑器预览一致**。

### 对照表

| 目标 | 产物 | 适用场景 | 可回灌 |
|---|---|---|---|
| `single_html` | 单个 `.html` | 直接投放、邮件内嵌、AD落地 | ❌ |
| `bundle` | `.zip` | 交接、归档、二次开发 | ✅ |
| `scaffold` | Vite 工程目录 | 交给前端继续开发 | ✅（含 schema.json） |
| `mautic` | 投递到 Mautic | 直接上线 | — |

---

## 2. lint 门禁

除 `allow_lint_error=true` 外，导出前会重跑一次 lint。
存在 error 时返回 **422 + 完整 lint 结果**：

```json
{
  "detail": {
    "message": "可投递性检查未通过（2 个 error）",
    "lint": {
      "passed": false, "score": 60,
      "counts": {"error": 2, "warn": 3, "info": 1},
      "issues": [...]
    },
    "errors": [
      {"code": "missing_unsubscribe", "severity": "error",
       "message": "未找到退订链接，违反 GDPR / CAN-SPAM，存在封发风险",
       "fix": "添加 email.footer 组件并填写退订链接"}
    ]
  }
}
```

前端拿到 `e.lint` 后展示具体问题与修复建议。

---

## 3. single_html

### 产出

```ts
{
  "filename": "eurocup-报名成功收口页.html",
  "html": "<!DOCTYPE html>...",
  "css": "/* design tokens */",
  "kind": "landing"
}
```

邮件是自包含的单文件（inline CSS + 少量 `<style>` 补丁）；
落地页也是单文件（CSS 全内联），可直接上传到任意静态托管。

### 直接下载

```http
GET /api/v1/contents/{id}/download?version=3
```

响应头用了 RFC 5987 编码以支持中文文件名：

```
Content-Disposition: inline; filename="eurocup-_____.html"; filename*=UTF-8''eurocup-报名成功收口页.html
```

> 实现细节：`Content-Disposition` 只允许 latin-1 字符，直接塞中文会报
> `UnicodeEncodeError`。因此同时给 ASCII 兜底名与 `filename*`。

---

## 4. bundle（推荐用于交接）

### zip 内容

```
eurocup-报名成功收口页-CMP_V1/
├── index.html              # 可直接打开的单文件产物
├── tokens.css              # 24 个 design token，换肤改这里
├── schema.json             # 结构化源文件，可回灌继续编辑
├── campaign-edit.json      # 生成元信息（来源、版本、kind）
└── README.md               # 使用说明 + token 表 + 交接清单
```

表单类型额外产出：

```
└── fields.json             # 字段清单，供 CRM / 数据层消费
```

### README 内容

```markdown
# EURO 2028 赛事营销活动页

- 类型：着陆页/活动站点（`landing`）
- Key：CMP_CUP2028_MAIN_V1
- 语言：zh-CN
- 主题：csts-dark-brand
- 生成工具：Campaign Edit 0.1.0

## 文件说明
| `index.html` | 可直接打开的单文件产物 |
| `tokens.css` | 设计 token（颜色/间距/圆角），改这里即可换肤 |
| `schema.json` | 结构化源文件，可重新导入 Campaign Edit 继续编辑 |

## 重新导入
curl -X POST http://localhost:8000/api/v1/contents \
  -H 'Content-Type: application/json' \
  -d @schema.json

## 主题 token
| token | 值 | 说明 |
|---|---|---|
| `--brand` | `#c8102e` | 品牌主色（CTA/强调） |
| ... | ... | ... |

## 注意
- 邮件产物已做 Outlook/Gmail 兼容处理；修改结构后建议重新跑一次可投递性检查。
- 落地页/表单产物请自行接入 Analytics 与真实 endpoint。
- 图片为外链，投放前请确认热链策略与版权。
```

**`schema.json` 是可回灌的关键**：
内容不在这个系统里改了，也不丢——改完 schema 导回来即可。

---

## 5. scaffold（Vite 工程）

给前端继续开发用。

```
eurocup-活动页-scaffold/
├── index.html              # 入口（head meta 已提取，style/script 已拆分）
├── package.json            # vite + build/dev 脚本
├── vite.config.js# base: './'，便于部署到子路径
├── .gitignore
├── campaign-edit.json
├── README.md               # 交接清单（含待办项）
└── src/
    ├── styles/
    │   ├── tokens.css      # design token
    │   └── components.css  # 从单文件 HTML 中抽出的组件样式
    ├── main.js             # 行为增强（倒计时/表单/埋点）
    └── schema.json         # 结构化源数据
```

### 拆分逻辑

```python
entry_html = render(schema, tokens=toks)
css_body   = _extract_style(entry_html)     # <style> 内容 → components.css
head_extra = _extract_head_meta(entry_html) # <meta> 标签 → index.html
body       = _extract_body(entry_html)      # 去掉 style/script → index.html
```

`base: './'` 是刻意设的——很多营销页部署在
`https://site.com/campaign/euro/` 这类子路径，绝对路径会 404。

### README 交接清单

```markdown
## 交接清单
- [ ] 替换占位图片为正式物料
- [ ] 接入真实表单 endpoint（`src/main.js`）
- [ ] 补 Analytics / 埋点事件
- [ ] 跑 Lighthouse 与多端真机验证
- [ ] 交回schema.json 以保持设计系统一致
```

最后一条是关键：**前端改完把 schema 导回来**，
避免设计系统分裂成"系统里的版本"和"Git 里的版本"两份。

---

## 6. Mautic 投递

### 映射关系

| 本系统 kind | Mautic 端点 | 关键字段 |
|---|---|---|
| `email` | `POST /api/emails/new` | `name` `subject` `customHtml` `isPublished` |
| `form` | `POST /api/forms/new` | `name` `fields[]` `postableHtml` `formTemplate` |
| `landing` | `POST /api/pages/new` | `title` `alias` `customHtml` |

### 已规避的线上坑

以下每一条都来自真实故障，写在 `export/mautic.py` 的注释里：

#### 坑 1：PUT 必须传完整对象

Mautic 7（API Platform 版）对 partial payload 调 `jms_serializer` 会 **500**。

```python
if update_id:
    existing = client.fetch_full(f"/api/emails/{update_id}")   # 先 GET 全量
    payload = {**existing, "name": name, "subject": subject,
               "customHtml": html, "isPublished": bool(publish)}
    client.put(f"/api/emails/{update_id}", payload)             # 再 PUT 全量
```

#### 坑 2：路由版本

部分端点在 `/api/v2`，部分在 `/api`。客户端提供fallback：

```python
def api2(self, path, method="GET", payload=None):
    code, data = self._request(method, f"/api/v2{path}", payload)
    if code == 404:
        return self._request(method, f"/api{path}", payload)
    return code, data
```

#### 坑 3：页面跳转靠 customHtml

Mautic 的 `redirectType` / `redirectUrl` 在 `mautic_code_mode` 下会被
构建逻辑忽略，**真正生效的是 customHtml 里的跳转代码**。

```python
def _inject_redirect(html: str, url: str) -> str:
    tag = (f'<meta http-equiv="refresh" content="0;url={url}">'
           f'<script>setTimeout(function(){{window.location.replace({json.dumps(url)})}},0);</script>')
    return html.replace("</head>", f"{tag}</head>", 1)
```

meta-refresh 兼容老浏览器，JS 兼容严格 CSP 环境，两者都写。

#### 坑 4：不做 DELETE

Mautic 的 DELETE 是硬删除，误删无法恢复。本系统只提供软下线：

```python
def set_published(client, asset_type, asset_id, published):
    action = "publish" if published else "unpublish"
    client.api2(f"/{plural}/{asset_id}/{action}", "PUT")   # isPublished = false
```

#### 坑 5：表单字段名冲突

Mautic 有保留字段名（`id` `form` `lead` `email` `name` ...），
冲突会**静默丢数据**。

```python
MAUTIC_RESERVED_FIELDS = {"id","form","lead","ip","date","landing_page",
                          "url","title","description","name","email",
                          "firstname","lastname","company","phone","country",
                          "city","postcode","address","message","consent",
                          "locale","timezone"}

if safe in MAUTIC_RESERVED_FIELDS:
    safe = f"custom_{safe}"
    warnings.append(f"字段 {name} 映射到 Mautic 保留字，已重命名为 {safe}")
```

冲突与重命名都会通过 `warnings` 返回给前端，不静默处理。

### 投递前查重

`discover_assets()` 可按关键字列出已有资产：

```http
GET /api/v1/contents/{id}/... →（示例）
POST /api/v1/plugins/...     →（见 mautic.py::discover_assets）
```

对接前先查，避免重复创建。返回格式：

```json
{
  "emails": {"total": 42, "items": [{"id": 91, "name": "EM_WELCOME", "isPublished": true}]},
  "forms":  {"total": 7,  "items": [{"id": 12, "name": "FORM_REG",  "isPublished": true}]},
  "pages":  {"total": 5,  "items": [{"id": 4,  "name": "CMP_MAIN",  "alias": "cmp-main"}]}
}
```

### 配置

```bash
MAUTIC_API_ENABLED=true
MAUTIC_BASE_URL=https://automarketing.example.com
MAUTIC_USERNAME=xxx
MAUTIC_PASSWORD=xxx
```

未配置时导出 `mautic` 目标返回 400 + 明确提示，不会静默失败。

---

## 7. 导出任务记录

每次导出写一条 `export_jobs`，失败也记录：

| 字段 | 说明 |
|---|---|
| `target` | 导出目标 |
| `status` | `success` / `failed` |
| `result` | 产物路径、文件列表、lint 摘要 |
| `error` | 失败原因（截断 2000 字符） |

排查"昨天那封邮件导出的文件在哪"这类问题时，
先查这张表而不是翻文件系统。

---

## 8. 邮件产物的可投递性

邮件导出不是"把 HTML 存下来"，而是经过一轮强制规范化的产物。

### 已在渲染器中强制的

| 约束 | 实现 |
|---|---|
| table 布局 | `<table role="presentation">` 包裹所有块 |
| inline CSS | 视觉属性写在元素 `style` 上 |
| 单容器宽度 | `max-width:600px` |
| 移动端 | `<style>` 里单media query，`.ce-pad` 降内边距、`.ce-stack` 堆叠 |
| Outlook 按钮 | `<!--[if mso]><v:roundrect>` VML 兜底 |
| 暗色模式 | `prefers-color-scheme` 补丁 |
| 多列移动端 | `.ce-hide-mobile` 隐藏间隔列 |
| 图片 alt | lint 校验，无 alt 报 warn |
| 退订链接 | 缺失报 **error**，阻断导出 |

### 建议的投递前检查清单

邮件端：
- [ ] 在 Litmus / Email on Acid 跑一遍主流客户端
- [ ] Gmail 桌面版 +移动版（会剥离 `<style>`，需确认 inline 部分完整）
- [ ] Outlook 2016/ 2021（Word 渲染引擎）
- [ ] QQ 邮箱 / 163 邮箱（国产客户端对 CSS 支持弱）
- [ ] Apple Mail（支持最好，作为基准）
- [ ] 确认 UTM 参数已拼接

落地页端：
- [ ] 移动端 390px 无横向滚动
- [ ] 表单 endpoint 已配，UTM 透传正常
- [ ] 图片有热链策略与版权确认
- [ ] Analytics / 埋点事件已接
- [ ] Lighthouse 无严重问题
- [ ] 关键 CTA 在首屏可见

表单端：
- [ ] 必填校验、格式校验生效
- [ ] UTM 隐藏域回填正确
- [ ] 隐私政策链接可点（GDPR）
- [ ] 反垃圾机制启用
- [ ] 字段名与 CRM 映射一致

---

## 9. 建议的交付流程

```
运营用意图控制台生成草稿
        ↓
内容库筛选 status=draft → 编辑器精修
        ↓
lint 通过（error=0）→ 提交审核（in_review）
        ↓
设计确认视觉 → 通过（approved）
        ↓
┌───────────────┬────────────────┐
│ 需要继续开发│ 直接上线           │
│ ↓              │ ↓                │
│ 导出 scaffold  │ 导出 bundle     │
│ 交接前端        │ 运营/设计自行部署 │
│ ↓              │ 或投递 Mautic    │
│ 前端改完        │                │
│ 导回 schema.json│                │
└───────────────┴────────────────┘
        ↓
发布（published）
        ↓
归档（archived）—— 永不删除
```