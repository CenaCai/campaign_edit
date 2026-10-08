# 开发与部署

## 1. 环境要求

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.11+ | 开发用 3.13；生产镜像用 3.12 |
| Node.js | 20+ | 实测 22.22 |
| SQLite | 内置 | 零配置；生产建议 PostgreSQL 15+ |
| Docker（可选） | 24+ | 一键起栈 |

---

## 2. 本地开发

### 2.1 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# macOS / Linux
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload --port 8000
```

首次启动自动完成：建表 → 载入 52 个内置组件 → 16 套模板 →
5 套主题 → 3 个项目 → 7 份示例内容 → 安装示例插件。约 3 秒。

API 文档：<http://localhost:8000/docs>

### 2.2 前端

```bash
cd frontend
npm install
npm run dev
```

访问 <http://localhost:5173>。Vite 已配好 `/api` 与 `/exports` 代理到 8000。

### 2.3 数据库维护

```bash
cd backend

# 首次初始化（或重置内置模板/主题）
.venv\Scripts\python -m app.seed

# 强制重置内置模板与主题（不会删内容）
.venv\Scripts\python -c "from app.seed.bootstrap import seed_all; print(seed_all(None, force=True))"

# 完全重置（危险：会删所有内容）
rm -r data/campaign_edit.db   # Windows: rmdir /s /q data
```

### 2.4 端到端冒烟测试

```bash
# 终端 A
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# 终端 B
.venv\Scripts\python scripts/smoke_test.py
```

覆盖 **74 项断言**：鉴权 → 模板 → 意图识别 → 渲染 → 版本/协作/审核 → 导出 → 插件 → MCP。

```
通过 74 / 失败 0（共 74）
```

### 2.5 前端构建

```bash
cd frontend

npm run build           # 类型检查 + 构建
npm run build:only      # 只构建（跳过类型检查）
npm run type-check      # 只做类型检查
```

**Windows 上esbuild 的常见问题**：

若报 `The package "@esbuild/win32-x64" could not be found`，
说明 npm 跳过了 optionalDependencies。修复：

```bash
npm install --no-save --include=optional @esbuild/win32-x64@0.24.2
```

（版本号与你的 vite 版本匹配，可从 `node_modules/esbuild/package.json` 里查。）

---

## 3. Docker 部署

### 3.1 一键起栈

```bash
cd deploy
cp .env.example .env

# 至少要改这两项
# JWT_SECRET 与 BOOTSTRAP_ADMIN_PASSWORD
```

生成强随机 secret：

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

启动：

```bash
docker compose up -d
docker compose logs -f api

# 访问
# http://localhost:8088
```

### 3.2 启用 PostgreSQL

```bash
# .env 里改
DATABASE_URL=postgresql+psycopg://ce:CHANGE_ME@db:5432/campaign_edit
POSTGRES_PASSWORD=CHANGE_ME
```

启动时带上 profile：

```bash
docker compose --profile postgres up -d
```

> `backend/requirements.txt` 里 `psycopg` 默认注释掉了，
> 生产镜像需要取消注释（或在 Dockerfile 里加装）。

### 3.3 架构

```
                     ┌─────────────┐
   :8088 ──────────► │ nginx (web) │ 静态资源 + SPA
                     │             │ /api → api:8000
                     └──────┬──────┘
                            │
                     ┌──────▼──────┐
                     │  api:8000   │ FastAPI（2 workers）
                     │             │
                     ├─────────────┤
                     │  db:5432    │ PostgreSQL（可选）
                     └──────┬──────┘
                            │ volume
              ┌─────────────┴─────────────┐
              │   ce-data  ce-plugins     │
              │  (SQLite/产物)  (插件包)   │
              └───────────────────────────┘
```

### 3.4 数据卷

| 卷 | 容器路径 | 内容 |
|---|---|---|
| `ce-data` | `/app/data` | SQLite DB、导出产物、静态资源 |
| `ce-plugins` | `/app/plugins` | 已安装插件包 |
| `ce-pgdata` | `/var/lib/postgresql/data` | PostgreSQL 数据 |

备份只需备份这些卷 + `.env`。

---

## 4. 生产配置清单

### 必改项

```bash
APP_ENV=production
APP_DEBUG=false

# 强随机，48 字节以上
JWT_SECRET=<python -c "import secrets; print(secrets.token_urlsafe(48))">

# 首次启动的管理员口令
BOOTSTRAP_ADMIN_PASSWORD=<强密码>

# CORS 精确指定，不要用 *
CORS_ORIGINS=https://campaign.example.com
```

### 强烈建议

```bash
# PostgreSQL（支持多 worker）
DATABASE_URL=postgresql+psycopg://ce:pass@db:5432/campaign_edit

# 保持远程安装关闭
PLUGIN_ALLOW_REMOTE_INSTALL=false
```

### 可选能力

```bash
# 意图识别 LLM（不配置也能跑，规则通道）
LLM_ENABLED=true
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=deepseek-chat

# Mautic 投递
MAUTIC_API_ENABLED=true
MAUTIC_BASE_URL=https://automarketing.example.com
MAUTIC_USERNAME=xxx
MAUTIC_PASSWORD=xxx
```

### 反向代理注意

若用 Nginx 代理 API：

```nginx
proxy_pass http://127.0.0.1:8000;
proxy_read_timeout 120s;    # 导出大内容可能慢
client_max_body_size 32m;   # 插件 zip 上传
proxy_set_header X-Forwarded-Proto $scheme;
```

---

## 5. 安全清单

上线前逐项确认：

- [ ] `JWT_SECRET` 已改为强随机（非默认值）
- [ ] `BOOTSTRAP_ADMIN_PASSWORD` 已改
- [ ] `APP_DEBUG=false`
- [ ] `CORS_ORIGINS` 精确指定，未使用 `*`
- [ ] 前端通过 HTTPS 提供服务
- [ ] 数据库不在公网暴露
- [ ] `PLUGIN_ALLOW_REMOTE_INSTALL=false`（或已评估风险）
- [ ] `MAUTIC_PASSWORD` 未硬编码在前端代码中
- [ ] `LLM_API_KEY` 未提交到 Git
- [ ] 定期备份 `data/` 与 `plugins/`

### 内置的安全措施

| 项 | 实现 |
|---|---|
| 密码存储 | PBKDF2-SHA256 + 随机盐，12 万次迭代 |
| 令牌 | HS256 JWT，标准库实现，12 小时过期 |
| SQL 注入 | SQLAlchemy 参数化，无字符串拼接 SQL |
| XSS | 渲染器 `_sanitize_*_html()` 剥离 script/事件属性/CSS 表达式 |
| 开放重定向 | `_sanitize_url()` 拦 `javascript:` / `data:` |
| zip-slip | 插件解压校验路径未逃逸 |
| 上传体积 | manifest ≤512KB，资源 ≤8MB，nginx 32MB |
| CORS | 白名单精确匹配 + credentials |
| 错误信息 | 生产不回显堆栈 |

**已知未覆盖**：

- 登录失败次数限制（需在网关层做，如 fail2ban 或 WAF）
- 刷新令牌与主动吊销（当前 JWT 签发后无法撤销，靠 12h 过期控制）
- 字段级权限（当前只有角色级：admin / editor / designer / viewer）

---

## 6. 监控建议

### 健康检查

```http
GET /api/v1/health          # 无需鉴权，容器 HEALTHCHECK 用
GET /api/v1/health/deep     # 需鉴权，探测 LLM 与 Mautic 连通性
```

### 关键指标

| 指标 | 告警阈值 | 意义 |
|---|---|---|
| `/health` 状态非 ok | 立即 | 服务不可用 |
| 意图识别 p95 延迟 | >5s | LLM 变慢，考虑降级 |
| `needs_confirm` 比例 | >60% | 词典需要补词，或 LLM 质量下降 |
| `intent_rule_wins` 比例 | >80% | LLM 通道可能失效 |
| 导出失败率 | >5% | 模板或渲染器可能有问题 |
| 插件 `status=broken` | 立即 | 插件同步失败 |

### 日志

```bash
docker compose logs -f api | grep -E "WARNING|ERROR"
```

启动时会打印引导统计：

```
引导完成: {'themes': 5, 'templates': 16, 'users': 4, 'projects': 3, 'contents': 7}
```

`templates: 0` 或 `contents: 0` 说明 seed 有问题，需要看 WARNING 日志。

---

## 7. 升级流程

```bash
# 1. 备份
sqlite3 backend/data/campaign_edit.db ".backup '/backup/ce-$(date +%F).db'"
tar czf /backup/plugins-$(date +%F).tar.gz backend/plugins/

# 2. 拉代码
git pull

# 3. 更新依赖（requirements.txt 可能有变）
cd backend && .venv/Scripts/pip install -r requirements.txt

# 4. 重启
docker compose restart api

# 5. 验证
curl http://localhost:8000/api/v1/health
.venv/Scripts/python scripts/smoke_test.py
```

### 数据库迁移

当前用 `Base.metadata.create_all()`（无破坏性变更时自动补表）。
若后续引入 Alembic：

```bash
alembic revision --autogenerate -m "add xxx"
alembic upgrade head
```

**迁移前务必备份**——`create_all()` 不会删列，但迁移脚本会。

---

## 8. 常见问题

### Q:意图识别不准

1. 先看界面上的「规则命中证据」，找到是哪个词误导了系统
2. 检查该类 `direct` 词库是否覆盖真实运营话术
3. 看 `explanation.note` 判断是规则判的还是 LLM 判的
4. 仍然不准再调 `INTENT_RULE_WEIGHT` / `INTENT_MIN_CONFIDENCE`

详见 `02-intent.md` §8。

### Q: 邮件在 Outlook 里布局散架

大概率是内容里用了 `position` / `flex` / `grid` / CSS 变量。
lint 应该已经报 error——如果没报，检查是不是通过 `generic_html` 组件
塞了原始 HTML（富文本清洗只剥离危险属性，不校验 CSS 属性支持度）。

### Q: 导出失败但看不出原因

```sql
SELECT target, status, substr(error, 1, 200), created_at
FROM export_jobs WHERE status = 'failed' ORDER BY created_at DESC LIMIT 10;
```

### Q: 前端构建报 esbuild 找不到

见 §2.5 的 Windows 问题。

### Q: 想清空所有示例数据

```sql
DELETE FROM content_versions;
DELETE FROM comments;
DELETE FROM review_tasks;
DELETE FROM contents;
DELETE FROM export_jobs;
DELETE FROM intents;
-- 保留 templates / themes / users / projects
```

或直接删 `data/campaign_edit.db` 重启（会重新 seed 示例内容，
需要的话把 `seed/demo.py` 的 `DEMO_CONTENTS` 清空）。

### Q: 如何新增用户

```python
# backend 目录
.venv\Scripts\python -c "
from app.db import SessionLocal
from app.models import User
from app.deps import hash_password
db = SessionLocal()
db.add(User(email='new@corp.com', name='新同事', role='editor',
            password_hash=hash_password('初始密码')))
db.commit(); print('created')
"
```

### Q: 生产能否用 SQLite + 多 worker

不能。SQLite 写操作串行化，多 worker 会大量 `database is locked`。
生产请换 PostgreSQL，开发/小团队（<10 并发编辑）用 SQLite + 单 worker 没问题。

---

## 9. 环境变量速查

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | development | `production` 时不回显堆栈 |
| `APP_DEBUG` | true | 生产务必false |
| `DATABASE_URL` | sqlite:///./data/campaign_edit.db | |
| `JWT_SECRET` | change-me-in-production | **必改** |
| `JWT_TTL_SECONDS` | 43200 | 12 小时 |
| `AUTH_DISABLED` | false | 本地演示可 true 跳过鉴权 |
| `BOOTSTRAP_ADMIN_EMAIL` | admin@csts.dev | |
| `BOOTSTRAP_ADMIN_PASSWORD` | admin12345 | **必改** |
| `LLM_ENABLED` | true | |
| `LLM_BASE_URL` | https://api.deepseek.com/v1 | OpenAI 兼容 |
| `LLM_API_KEY` | 空 | 不配置则走规则通道 |
| `LLM_MODEL` | deepseek-chat | |
| `LLM_TIMEOUT_SECONDS` | 30 | |
| `INTENT_RULE_WEIGHT` | 0.45 | 规则通道权重 |
| `INTENT_LLM_WEIGHT` | 0.55 | LLM 通道权重 |
| `INTENT_MIN_CONFIDENCE` | 0.35 | 低于则需人工确认 |
| `INTENT_AUTO_TEMPLATE_SCORE` | 0.55 | 模板匹配分门槛 |
| `EXPORT_DIR` | ./data/exports | |
| `ASSET_DIR` | ./data/assets | |
| `PLUGIN_DIR` | ./plugins | |
| `PLUGIN_ALLOW_REMOTE_INSTALL` | false | 安全默认 |
| `MAUTIC_API_ENABLED` | false | |
| `MAUTIC_BASE_URL` | 空 | |
| `CORS_ORIGINS` | http://localhost:5173 | 逗号分隔 |