# 数据模型与协作

## 1. 表结构总览

```
users ──────┐
            ├── contents ──┬── content_versions   （不可变版本快照）
projects ───┤             ├── comments            （区块锚定评论）
            │             ├── review_tasks        （审核流转留痕）
            │             └── export_jobs         （导出任务记录）
            ├── templates ──── themes
            ├── intents       （意图识别日志）
            └── plugins
```

共 10 张表。SQLAlchemy 2.0 声明式，JSON 字段用于存 schema 与配置。

---

## 2. 核心表

### 2.1 contents —— 三类内容共用

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str(32) | uuid hex |
| `key` | str(96) | 对外标识，遵循 `EM_` / `FORM_` / `CMP_` 前缀规范 |
| `name` | str(200) | 显示名 |
| `kind` | str(16) | `email` / `form` / `landing` |
| `status` | str(16) | `draft` / `in_review` / `approved` / `published` / `archived` |
| `locale` | str(16) | `zh-CN` / `en-GB` / `en-US` |
| `project_id` | FK | 所属项目（工作空间） |
| `template_id` | FK | 来源模板 |
| `theme_id` | FK | 主题 |
| `intent_id` | FK | 来源意图识别记录 |
| `current_version` | int | 当前版本号 |
| `current_version_id` | str | 当前版本 ID |
| `published_version_id` | str | 已发布版本（可与当前不同） |
| `lock_owner_id` | str | 草稿锁持有者 |
| `lock_expires_at` | datetime | 锁过期时间 |
| `lock_version` | int | **乐观锁**，每次保存 +1 |
| `export_path` | str(500) | 最近导出产物路径 |
| `mautic_asset_id` | int | 已投递的 Mautic 资产 ID |
| `meta` | JSON | 业务元信息（意图来源、备注等） |

索引：`(kind, status)`、`(project_id, status)`。

### 2.2 content_versions —— 只追加

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str(32) | |
| `content_id` | FK | |
| `version` | int | 与 `content_id` 唯一约束 |
| `schema` | JSON | **完整 Block Schema 快照** |
| `version_meta` | JSON | `{ message, rollback_from }` |
| `diff` | JSON | 与上一版的结构化差异 |
| `rendered_html` | text | 渲染快照（截断 400KB） |
| `lint_result` | JSON | 该版本的 lint 结果 |
| `author_id` / `author_name` | |作者 |
| `created_at` | datetime | |

**没有 UPDATE 路径**。`_append_version()` 是唯一的写入函数。

### 2.3 结构化 diff

不使用文本 diff（JSON 文本 diff 噪音太大），而是按 schema 结构对比：

```json
{
  "summary": { "replace": 3, "add": 1, "remove": 0, "type_change": 0, "move": 0, "reorder": 1 },
  "changes": [
    {"op": "replace", "path": "root#b_x.props.text", "old": "立即购票", "new": "马上购票"},
    {"op": "add", "path": "root#b_new", "type": "email.button"},
    {"op": "reorder", "path": "root", "old": ["b_a","b_b"], "new": ["b_b","b_a"]},
    {"op": "type_change", "path": "root#b_c", "old": "landing.section", "new": "landing.hero"}
  ]
}
```

实现见 `blocks/schema.py::diff_nodes()`。

---

## 3. 版本管理

### 3.1 写入：只追加

```python
def save_content(db, *, content, user, schema, message="",
                 create_version=True, lint_gate=True, lock_version=None, force=False):
    _assert_not_locked_by_other(content, user, force=force)     # 1. 草稿锁检查

    if lock_version is not None and lock_version != content.lock_version:
        raise ServiceError("版本冲突：内容已被他人更新", 409, ...)  # 2. 乐观锁 CAS

    normalized = normalize_schema(schema, get_registry())        # 3. 规范化（白名单过滤）

    pv = preview(normalized)                                    # 4. 渲染 + lint
    if lint_gate and not pv["lint"]["passed"]:
        raise ServiceError("可投递性检查未通过", 422, lint=..., errors=...)  # 5. 门禁

    _append_version(db, content=content, schema=normalized,     # 6. 追加版本
                    author=user, message=message,
                    lint_result=pv["lint"], rendered_html=pv["html"])
    content.updated_at = _now()
    db.commit()
```

### 3.2 回滚：也是追加

```python
def rollback(db, content, user, target_version, message=""):
    target = get_version(db, content, target_version)
    return _append_version(
        db, content=content, schema=target.schema, author=user,
        message=message or f"回滚到 v{target_version}",
        extra_meta={"rollback_from": target_version},
    )
```

版本链示例：

```
v1 ──→ v2 ──→ v3 ──→ v4（回滚自v2）
                  └─ schema == v2 的 schema，但 v1~v4 全部保留
```

### 3.3 为什么不做"原地改历史版本"

假设支持原地修改，那么：
上周五发的邮件，今天有人"修正"了 v2 的 schema，
审计链就断了——无法回答"当时发出去的到底是什么"。

内容系统里这个代价很高：投放出去的邮件是有法律意义的通信记录。

---

## 4. 多人协作

### 4.1 乐观锁（防覆盖写）

```
客户端保存时回传自己拿到的 lock_version
   ├─ 一致 → 保存成功，lock_version += 1
   └─ 不一致 → 409 + 当前 lock_version
              提示："内容已被他人更新，请刷新后重试"
```

**防的场景**：A 和 B 同时打开同一内容，A 保存后 B 再保存，
B 的改动不会被静默丢弃，而是收到明确冲突提示。

**不防的场景**：A、B 交替编辑不同区块，先后保存——
这是正常协作，两次保存都成功，diff 里能看到各自改了什么。

### 4.2 草稿锁（软独占 + TTL）

```
POST /contents/{id}/lock { action: "acquire", ttl_seconds: 300 }
   ├─ 无锁 / 已过期 / 锁属于自己 → 获得锁
   └─ 锁有效且属于他人 → 409 + { lock_owner, expires_at }

前端每 90s 发 heartbeat 续期
释放：POST /contents/{id}/lock { action: "release" }
```

**为什么用 TTL 而不是强锁**：进程崩溃 / 浏览器强杀会留下永久死锁。
TTL 让锁自动过期，配合前端心跳做到"活着就独占，死了就释放"。

归档内容时自动清空锁（见 `services.transition()`）。

### 4.3 评论：锚定到区块

```python
Comment(content_id, block_id="b_a1b2c3d4e5", body="按钮文案再短一点",
        resolved=False, author_id, author_name)
```

`block_id` 让评论能定位到具体区块：
- 大纲树上显示 💬 角标
- 属性面板显示该区块的未解决评论数
- 区块被删除时评论不会悬空（前端按 id 匹配，找不到就不显示）

### 4.4 审核状态机

```python
class ContentStatus:
    TRANSITIONS = {
        DRAFT:      (IN_REVIEW, ARCHIVED),
        IN_REVIEW:  (APPROVED, DRAFT, ARCHIVED),
        APPROVED:   (PUBLISHED, DRAFT, ARCHIVED),
        PUBLISHED:  (ARCHIVED, DRAFT),
        ARCHIVED:   (DRAFT,),
    }
```

典型流程（示例数据里的真实状态）：

```
运营草稿 → 提交审核 → 设计确认 → 通过 → 前端发布
  draft    in_review    approved    published
             │
             └──→ 意见不合 → draft（回退重改）
```

非法迁移返回 **409 + 可选项列表**：

```json
{
  "detail": {
    "message": "非法状态迁移：已发布 → 审核中",
    "allowed": ["已归档", "草稿"]
  }
}
```

发布需要 `admin` 或 `editor` 角色（`designer` 不能发布）。

每次流转写一条 `review_tasks`，含 `from_status` / `to_status` /
`reason` / `state` / `assignee_id` / `decided_by` / `decided_at`。

---

## 5. 意图识别日志（intents）

每次 `POST /api/v1/intents` 落一条：

| 字段 | 说明 |
|---|---|
| `raw_text` | 原始输入 |
| `engine` | `rule` / `llm` / `hybrid` |
| `status` | `resolved` / `need_confirm` |
| `content_type` | 识别出的类型 |
| `confidence` | 置信度 |
| `slots` | 抽取的槽位 |
| `plan` | 多资产计划（含模板候选与追问） |
| `candidates` | 三通道得分 |
| `explanation` | 仲裁过程、场景、渠道、说明 |
| `rule_scores` | 各类型规则分 |
| `llm_payload` | LLM 错误与告警 |
| `latency_ms` | 耗时 |
| `accepted` | 是否被采纳并落地 |
| `result_content_ids` | 生成的内容 ID 列表 |

**价值**：
- 识别错了可以回溯「当时为什么这么判」
- 耗时统计能发现 LLM 变慢
- `accepted=false` 且 `needs_confirm` 比例高 → 说明词典需要补词

---

## 6. 导出任务（export_jobs）

| 字段 | 说明 |
|---|---|
| `content_id` / `version_id` | 导出的对象与版本 |
| `target` | `single_html` / `bundle` / `scaffold` / `mautic` |
| `status` | `success` / `failed` |
| `options` | 请求参数 |
| `result` | 产物路径、lint 摘要、消息 |
| `error` | 失败原因（截断 2000 字符） |

失败也落库（`status=failed` + `error`），便于排查导出相关问题。

---

## 7. 存储选型

### SQLite（默认）

```python
DATABASE_URL = "sqlite:///./data/campaign_edit.db"
# 连接时启用：
PRAGMA journal_mode = WAL      # 读写并发
PRAGMA foreign_keys = ON       # 外键约束
PRAGMA busy_timeout = 8000     # 锁等待
```

**适合**：单机部署、小团队（<10 并发编辑）、演示环境。

**限制**：写操作串行化，不适合多 worker。

### PostgreSQL（生产推荐）

```bash
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/campaign_edit
pip install "psycopg[binary]"
```

**优势**：真正的并发写、JSONB 索引（可对 `schema` 做结构化查询）、
`jsonb_path_ops` 支持按块 ID 检索。

### 迁移到 Postgres

```bash
# 1. 备份 SQLite
sqlite3 backend/data/campaign_edit.db .dump > backup.sql

# 2. 建库并导入（用 pandas 或 pgloader）
pgloader sqlite:///backend/data/campaign_edit.db postgresql://ce:pass@db/campaign_edit

# 3. 改环境变量并重启
DATABASE_URL=postgresql+psycopg://ce:pass@db/campaign_edit
```

表结构本身无需改动——用的是 SQLAlchemy 声明式，SQLite 与 PG 的
JSON 类型都支持（Dialect 层面自动映射为 JSON / JSONB）。

---

## 8. 备份

### SQLite

```bash
# 热备份（不锁库）
sqlite3 backend/data/campaign_edit.db ".backup '/backup/ce-$(date +%F).db'"

# 导出 SQL（跨版本更安全）
sqlite3 backend/data/campaign_edit.db .dump | gzip > backup-$(date +%F).sql.gz
```

### PostgreSQL

```bash
pg_dump -Fc ce > /backup/ce-$(date +%F).dump
pg_restore -d ce --clean /backup/ce-2026-10-08.dump
```

### 需要一起备份的

| 路径 | 内容 | 重要性 |
|---|---|---|
| `backend/data/campaign_edit.db` | 内容与版本 | ★★★ |
| `plugins/` | 第三方插件包 | ★★ |
| `backend/data/exports/` | 导出产物 | ★（可重新生成） |
| `deploy/.env` | 配置与密钥 | ★★★ |

版本数据不可再生——内容是唯一的，导出产物可以随时重新生成。