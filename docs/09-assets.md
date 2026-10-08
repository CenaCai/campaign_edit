# Asset 资产层

## 1. 为什么需要这一层

原方案里，导出产物中的图片全是外链 URL。这在实践中有两个问题：

1. **交付不可自包含** —— 客户拿走 zip 后，图片还依赖生产环境的资源地址
2. **运营被迫做技术决策** —— "图片要不要下载""热链会不会挂""要不要内联"

因此引入 Asset 层：图片先入库拿到稳定 key，导出时按目标场景决定落地方式。

```
上传图片
   ↓
Asset 表（按内容哈希去重：同一张logo 被 20 封邮件引用只存一份）
   ↓
组件的 src 属性填 **asset key**（不是 URL）
   ↓
导出时按目标场景处理
   ├── 邮件    → data URI 内联（客户端不认相对路径）
   ├── 落地页  → 复制进 assets/，产物自包含
   └── CDN     → 替换为对象存储 URL
```

---

## 2. 存储适配器

位置：`backend/app/assets/storage.py`

| 适配器 | 用途 | 依赖 |
|---|---|---|
| `LocalStorage` | 开发、内网、对象存储接入前的过渡 | 零依赖（标准库） |
| `S3Storage` | S3 / MinIO / OSS（S3 兼容 API） | `boto3`（延迟导入） |

切换只需一个环境变量：

```bash
ASSET_BACKEND=local   # 默认
ASSET_BACKEND=s3
S3_BUCKET=your-bucket
S3_REGION=eu-west-1
S3_ENDPOINT=              # MinIO/OSS 填这个
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_PUBLIC_BASE=https://cdn.example.com
```

### key 规范

```
asset/<yyyy-mm>/<sha256前16位>.<ext>
例：asset/2026-10/497790947d466676.png
```

用内容哈希而非时间戳做 key 的原因：**同一张图重复上传得到同一个 key**，
天然去重，且换存储后端时历史 key 依然有效。

### 安全措施

| 措施 | 实现 |
|---|---|
| 路径穿越 | `LocalStorage._safe_path()` 解析后校验仍在 root 内 |
| 半截文件 | 先写 `.tmp` 再 `os.replace()` 原子改名 |
| MIME 欺骗 | **魔数优先**，不信客户端 MIME 与扩展名 |
| SVG XSS | 扫描 `<script>` / `javascript:` / `onload=` / `<foreignobject>` 等 |
| 超大文件 | `ASSET_MAX_BYTES` 默认 20MB |
| 类型白名单 | 只允许 PNG/JPEG/GIF/WebP/AVIF/SVG |

---

## 3. 纯标准库的图片解析

不引 Pillow。用魔数 + 文件头解析出类型与尺寸：

```python
sniff_mime(data)   # PNG/JPEG/GIF/WebP/AVIF/SVG
image_size(mime, data)  # PNG: IHDR / JPEG: SOF 段扫描 / GIF: 逻辑屏 / WebP: VP8 变体
```

实测 1×1 PNG → `("image/png", 1, 1)`。

---

## 4. 引用分析

`collect_asset_refs(schema)` 递归扫描 schema，找出所有引用资产 key 的 props：

```python
_ASSET_PROPS = {"src", "image", "poster", "bg_image", "background_image",
                "logo_image", "logo", "map_embed", "embed_url"}
```

同时处理数组字段里嵌套的对象（票档卡、FAQ、社交链接等）：

```json
{"type": "landing.ticket_cards",
 "props": {"cards": [{"image": "asset/2026-10/abc.png", "name": "套票"}]}}
```

`map_embed` / `embed_url` 排除在外——它们是 iframe 嵌入，不是静态资源。

### 导出前校验

```http
POST /api/v1/contents/{id}/export
```

会先跑 `validate_assets()`：

- 引用的本地资产不存在 → **422 阻断导出**（返回缺失的 key 列表）
- 图片缺 alt → warn 级，在 `job.result.assets.no_alt` 里返回
- 强制导出：`options.allow_missing_assets=true`

---

## 5. 三种落地策略

在导出请求里指定：

```json
{ "options": { "asset_mode": "auto" } }
```

| 模式 | 行为 | 适用 |
|---|---|---|
| `auto`（默认） | 邮件走 inline，其余保持原样 | 通用 |
| `inline` | ≤3MB 转 data URI，超过则改用绝对 URL | 邮件 |
| `bundle` | 复制进产物 `assets/`，schema 里改成相对路径 | 落地页 / 表单 |
| `cdn` | 替换为资产 URL | 已配对象存储 |

> 为什么大图不内联：邮件客户端对 data URI 通常有 2~3MB 限制，
> 超过会显示裂图。超过阈值自动改用绝对地址。

`bundle` 模式产物的结构：

```
eurocup-收口页-CMP_V1/
├── index.html          # 里面的 <img src="assets/4977....png">
├── tokens.css
├── schema.json
├── campaign-edit.json
├── README.md           # 含"assets/ 有几个资源"与部署说明
└── assets/
    └── 497790947d466676.png
```

解压后 `index.html` + `assets/` 可直接部署，不需要任何外部依赖。

---

## 6. API

```http
POST   /api/v1/assets                    # 上传（multipart）
GET    /api/v1/assets                    # 列表（按 project/mime/关键词过滤）
GET    /api/v1/assets/status              # 存储后端状态与限额
GET    /api/v1/assets/{id}                # 详情 + 引用它的内容列表
GET    /api/v1/assets/{id}/data           # 读取图片内容
GET    /api/v1/assets/{id}/references     # 谁在引用
GET    /api/v1/assets/{id}/html-snippet    # 生成可插入的标签
DELETE /api/v1/assets/{id}?force=         # 删除（被引用时需 force）
```

### 删除保护

资产常被多份内容引用。默认只做软删除（`is_active=false`），
且当存在引用时返回 **409 + 引用清单**：

```json
{
  "detail": {
    "reason": "in_use",
    "referenced_by": [
      {"id": "abc", "key": "CMP_MAIN_V1", "name": "活动主页面", "status": "published"}
    ],
    "message": "该资产被 3 份内容引用，请先解除引用或使用 force"
  }
}
```

`force=true` 才会真正删除文件。

---

## 7. 前端使用流程

```typescript
// 1. 上传
const form = new FormData()
form.append('file', file)
form.append('alt', '2026 赛季套票')
const asset = await api.uploadAsset(form)

// 2. 填进组件（注意是 key，不是 url）
api.setProp(nodeId, 'src', asset.key)     // src = "asset/2026-10/abc.png"

// 3. 导出时自动处理
await api.exportContent(contentId, { target: 'bundle' })
```

编辑器里应把 `src` 渲染成图片预览而不是纯文本——
通过 `GET /api/v1/assets/{id}/html-snippet` 可以拿到可直接插入的 `<img>` 标签。

---

## 8. 配置项

```bash
ASSET_BACKEND=local              # local | s3
ASSET_DIR=./data/assets          # local 后端的落盘目录
ASSET_URL_PREFIX=/assets         # local 后端的 URL 前缀
ASSET_MAX_BYTES=20971520         # 20MB
ASSET_ALLOWED_MIMES=image/png,image/jpeg,image/gif,image/webp,image/svg+xml,image/avif
EXPORT_INLINE_ASSETS_THRESHOLD=3145728   # 3MB，超过则不内联
S3_BUCKET=
S3_REGION=
S3_ENDPOINT=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_PUBLIC_BASE=
```

---

## 9. 常见问题

### Q: 为什么不直接存 URL？

因为导出产物需要**自包含**。存 URL 时导出物依赖外部地址，
客户拿走后在离线环境或资源失效时就全是裂图。

### Q: SVG 为什么单独查脚本？

SVG 是 XML，可以内联 `<script>` 与事件属性，是投放场景的常见 XSS 载体。
上传时直接拒绝，而不是等到渲染时再过滤——因为到渲染时可能已被缓存。

### Q: 同一个文件被引用 20 次怎么存？

按内容哈希去重，磁盘上只有一份。`Asset` 表也只有一行记录，
20 处引用都指向同一个 `storage_key`。

### Q: 换存储后端需要改内容吗？

不需要。schema 里存的是 key 而不是 URL，
换后端后 key 不变，只是 `url` 解析方式变了。