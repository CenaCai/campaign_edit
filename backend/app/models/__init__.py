"""ORM 模型：用户/项目/内容/版本/模板/主题/插件/意图日志/审核/评论/导出任务。

设计要点
--------
1. 三类内容（email / form / landing）共用一张 ``contents`` 表，用 ``kind`` 区分，
   内容体统一为 Block Schema JSON（``current_schema``），这是意图识别 → 模板 → 编辑器
   → 导出 全链路唯一的数据契约。
2. 版本不可变：``content_versions`` 只追加不修改，``contents.current_version_id``
   指向当前生效版本，回滚 = 追加一个新版本（保留审计链）。
3. 多人协作：``contents.lock_owner`` + ``lock_expires_at`` 做草稿锁；
   ``lock_version`` 乐观锁字段防���覆盖写。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

# --- 枚举常量（用字符串而非 DB Enum，避免迁移痛苦） ---

class ContentKind:
    EMAIL = "email"
    FORM = "form"
    LANDING = "landing"
    ALL = (EMAIL, FORM, LANDING)
    LABEL = {EMAIL: "HTML 邮件", FORM: "表单", LANDING: "着陆页/活动站点"}

    @classmethod
    def check(cls, v: str) -> str:
        if v not in cls.ALL:
            raise ValueError(f"kind must be one of {cls.ALL}")
        return v


class ContentStatus:
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    ALL = (DRAFT, IN_REVIEW, APPROVED, PUBLISHED, ARCHIVED)
    LABEL = {
        DRAFT: "草稿",
        IN_REVIEW: "审核中",
        APPROVED: "已通过",
        PUBLISHED: "已发布",
        ARCHIVED: "已归档",
    }
    #: 允许的状态迁移边
    TRANSITIONS = {
        DRAFT: (IN_REVIEW, ARCHIVED),
        IN_REVIEW: (APPROVED, DRAFT, ARCHIVED),
        APPROVED: (PUBLISHED, DRAFT, ARCHIVED),
        PUBLISHED: (ARCHIVED, DRAFT),
        ARCHIVED: (DRAFT,),
    }

    @classmethod
    def can_transition(cls, src: str, dst: str) -> bool:
        return dst in cls.TRANSITIONS.get(src, ())


def _uuid() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    # pbkdf2_sha256$iterations$salt$hash —— 不存明文
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="editor")  # admin/editor/designer/viewer
    avatar: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    items: Mapped[list["Content"]] = relationship(back_populates="owner")


class Project(Base):
    """工作空间/项目，隔离不同品牌或赛事（如 CSTS / Waterbomb / EUROCUP）。"""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # CSTS 命名规范: CMP_/EM_/FORM_
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    brand_tokens: Mapped[dict] = mapped_column(JSON, default=dict)  # 品牌 design token 覆盖
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    contents: Mapped[list["Content"]] = relationship(back_populates="project")


class Theme(Base):
    """主题：design token 集合，导出为 CSS 变量。"""

    __tablename__ = "themes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(120))
    kind_scope: Mapped[str] = mapped_column(String(32), default="all")  # all/email/form/landing
    tokens: Mapped[dict] = mapped_column(JSON, default=dict)
    css_vars: Mapped[dict] = mapped_column(JSON, default=dict)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    source_plugin: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Template(Base):
    """模板：预置 Block Schema 骨架，带适用场景标签供意图匹配打分。"""

    __tablename__ = "templates"
    __table_args__ = (Index("ix_templates_kind_tags", "kind", "scenario"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16), index=True)
    scenario: Mapped[str] = mapped_column(String(64), default="generic")  # promo/welcome/recovery/...
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN")
    channel: Mapped[str] = mapped_column(String(64), default="")  # email/ads/social...
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)  # 中文关键词，参与意图匹配
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    thumbnail: Mapped[str] = mapped_column(String(255), default="")
    theme_id: Mapped[str | None] = mapped_column(ForeignKey("themes.id", ondelete="SET NULL"))
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_plugin: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Content(Base):
    """内容实体：邮件 / 表单 / 着陆页 共用。"""

    __tablename__ = "contents"
    __table_args__ = (
        Index("ix_contents_kind_status", "kind", "status"),
        Index("ix_contents_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(96), index=True)  # EM_/FORM_/CMP_ 前缀
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), default=ContentStatus.DRAFT, index=True)
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN")

    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    template_id: Mapped[str | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"))
    theme_id: Mapped[str | None] = mapped_column(ForeignKey("themes.id", ondelete="SET NULL"))
    intent_id: Mapped[str | None] = mapped_column(ForeignKey("intents.id", ondelete="SET NULL"))

    current_version: Mapped[int] = mapped_column(Integer, default=0)
    current_version_id: Mapped[str | None] = mapped_column(String(32))

    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # 草稿锁：谁在编辑 + 何时过期
    lock_owner_id: Mapped[str | None] = mapped_column(String(32))
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    # 乐观锁：每次保存 +1，前端提交时回传做 CAS
    lock_version: Mapped[int] = mapped_column(Integer, default=0)

    # 发布产物快照（导出/发布时填充）
    published_version_id: Mapped[str | None] = mapped_column(String(32))
    export_path: Mapped[str | None] = mapped_column(String(500))
    mautic_asset_id: Mapped[int | None] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    project: Mapped[Project | None] = relationship(back_populates="contents")
    owner: Mapped[User | None] = relationship(back_populates="items")
    versions: Mapped[list["ContentVersion"]] = relationship(
        back_populates="content", cascade="all, delete-orphan",
        order_by="ContentVersion.version",
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class ContentVersion(Base):
    """不可变版本快照。"""

    __tablename__ = "content_versions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    schema: Mapped[dict] = mapped_column(JSON, default=dict)
    version_meta: Mapped[dict] = mapped_column(JSON, default=dict)  # 提交信息/作者意图
    diff: Mapped[dict] = mapped_column(JSON, default=dict)           # 与上一版的 schema 级差异
    rendered_html: Mapped[str | None] = mapped_column(Text)
    lint_result: Mapped[dict | None] = mapped_column(JSON)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    content: Mapped[Content] = relationship(back_populates="versions")

    __table_args__ = (UniqueConstraint("content_id", "version", name="uq_content_version"),)


class IntentLog(Base):
    """意图识别日志：输入 → 结构化结果 → 采纳的模板/类型 → 生成的资产。"""

    __tablename__ = "intents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    raw_text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(16), default="zh")
    engine: Mapped[str] = mapped_column(String(32), default="hybrid")  # rule/llm/hybrid
    status: Mapped[str] = mapped_column(String(24), default="resolved")  # resolved/need_confirm/failed

    content_type: Mapped[str | None] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    slots: Mapped[dict] = mapped_column(JSON, default=dict)
    plan: Mapped[list] = mapped_column(JSON, default=list)  # 多资产计划
    candidates: Mapped[list] = mapped_column(JSON, default=list)
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    rule_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    llm_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    result_content_ids: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ReviewTask(Base):
    """审核任务（运营 → 设计/前端 → 发布）。"""

    __tablename__ = "review_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), index=True)
    version_id: Mapped[str | None] = mapped_column(String(32))
    from_status: Mapped[str] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str] = mapped_column(String(16), default="pending")  # pending/approved/rejected/cancelled
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Comment(Base):
    """协作评论，锚定到某个 block 或整篇内容。"""

    __tablename__ = "comments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    content_id: Mapped[str] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"), index=True)
    block_id: Mapped[str | None] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    author_name: Mapped[str] = mapped_column(String(80), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    content: Mapped[Content] = relationship(back_populates="comments")


class Plugin(Base):
    """已安装插件（组件包 / 主题包 / 模板包 / 意图规则包 / MCP 插件）。"""

    __tablename__ = "plugins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(32), default="0.0.0")
    kind: Mapped[str] = mapped_column(String(32))  # component/theme/template/intent_rule/mcp/bundle
    description: Mapped[str] = mapped_column(Text, default="")
    author: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(24), default="active")  # active/disabled/broken
    # 已注册的扩展：components / themes / templates / intent_rules / mcp_servers
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    # DB 列名避开 SQLAlchemy 声明式注册表的保留名 registry。
    # Python 属性也避开（用 runtime_state），对 API/前端仍以 registry 暴露：
    #   plugins.py:plugin_dict() 读 p.runtime_state
    #   plugins.py / services.py 用 p.runtime_state
    runtime_state: Mapped[dict] = mapped_column("registry", JSON, default=dict)
    install_path: Mapped[str | None] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(80), default="")
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    install_log: Mapped[dict] = mapped_column(JSON, default=dict)
    installed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ExportJob(Base):
    """导出任务记录。"""

    __tablename__ = "export_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    content_id: Mapped[str | None] = mapped_column(ForeignKey("contents.id", ondelete="CASCADE"))
    version_id: Mapped[str | None] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(24))  # email_single/landing_bundle/form_html/scaffold/mautic
    status: Mapped[str] = mapped_column(String(16), default="success")
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Asset(Base):
    """静态资产（图片为主）。

    存在的意义：让导出产物里的图片指向可控地址，而不是编辑器临时地址。
    按内容哈希去重（同一张 logo 被多份内容引用只存一份）。
    软删除：资产可能正被多份内容引用，删除前需检查引用关系。
    """

    __tablename__ = "assets"
    __table_args__ = (Index("ix_assets_project_active", "project_id", "is_active"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(160), index=True)   # 相对键 asset/2026-10/xxx.png
    storage_key: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    storage_backend: Mapped[str] = mapped_column(String(16), default="local")
    filename: Mapped[str] = mapped_column(String(200), default="")
    mime: Mapped[str] = mapped_column(String(80), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(600), default="")
    alt_text: Mapped[str] = mapped_column(String(300), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_svg_safe: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)