"""Pydantic 请求/响应模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------- auth

class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    name: str
    role: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------- blocks

class BlockOut(BaseModel):
    key: str
    name: str
    kind: list[str]
    category: str
    is_container: bool
    renderer: str
    props_schema: dict[str, Any]
    style_defaults: dict[str, Any]
    children_allowed: list[str] | None = None
    children_limit: dict[str, Any] | None = None
    source: str = "builtin"
    example: dict[str, Any] | None = None


# ---------------------------------------------------------------- intent

class IntentRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    use_llm: bool = True
    project_id: str | None = None
    auto_create: bool = False          # True = 识别后直接落库创建内容
    publish: bool = False


class IntentAssetOut(BaseModel):
    kind: str
    role: str
    purpose: str
    scenario: str
    locale: str
    slots: dict[str, Any]
    depends_on: list[str]
    template_id: str | None
    template_score: float
    template_candidates: list[dict[str, Any]]
    component_hints: list[str]
    followups: list[dict[str, Any]]


class IntentResponse(BaseModel):
    id: str | None = None
    ok: bool
    engine: str
    raw_text: str
    content_type: str | None
    confidence: float
    scenario: str
    locale: str
    slots: dict[str, Any]
    plan: list[IntentAssetOut]
    candidates: list[dict[str, Any]]
    rule_scores: dict[str, float]
    rule_evidence: list[dict[str, Any]]
    explanation: dict[str, Any]
    needs_confirm: bool
    conflicts: list[str]
    warnings: list[str]
    latency_ms: int
    degraded: bool
    llm_error: str = ""
    created_contents: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------- content

class ContentCreate(BaseModel):
    kind: Literal["email", "form", "landing"]
    name: str = Field(..., min_length=1, max_length=200)
    key: str | None = None
    locale: str = "zh-CN"
    project_id: str | None = None
    template_id: str | None = None
    theme_id: str | None = None
    schema_: dict[str, Any] | None = Field(None, alias="schema")
    model_config = ConfigDict(populate_by_name=True)


class ContentUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    locale: str | None = None
    theme_id: str | None = None
    meta: dict[str, Any] | None = None
    reason: str = ""
    lock_version: int | None = None      # 乐观锁：不匹配则 409


class ContentSave(BaseModel):
    """保存新版本。"""
    schema_: dict[str, Any] = Field(..., alias="schema")
    message: str = ""
    create_version: bool = True
    lint_gate: bool = True                # error 级问题是否阻止保存
    lock_version: int | None = None
    model_config = ConfigDict(populate_by_name=True)


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    key: str
    name: str
    kind: str
    status: str
    locale: str
    project_id: str | None
    template_id: str | None
    theme_id: str | None
    intent_id: str | None
    current_version: int
    current_version_id: str | None
    owner_id: str | None
    lock_owner_id: str | None
    lock_expires_at: datetime | None
    lock_version: int
    published_version_id: str | None
    export_path: str | None
    mautic_asset_id: int | None
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    content_id: str
    version: int
    version_meta: dict[str, Any]
    diff: dict[str, Any]
    author_name: str
    created_at: datetime


# ---------------------------------------------------------------- templates/themes

class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    key: str
    name: str
    kind: str
    scenario: str
    locale: str
    channel: str
    description: str
    tags: list[str]
    thumbnail: str
    usage_count: int
    is_active: bool
    source_plugin: str | None
    created_at: datetime


class ThemeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    key: str
    name: str
    kind_scope: str
    tokens: dict[str, Any]
    is_builtin: bool
    source_plugin: str | None


# ---------------------------------------------------------------- export

class ExportRequest(BaseModel):
    target: Literal["single_html", "bundle", "scaffold", "mautic"] = "bundle"
    version_id: str | None = None
    publish: bool = False
    update_mautic: bool = False
    redirect_url: str = ""
    allow_lint_error: bool = False
    options: dict[str, Any] = Field(default_factory=dict)


class ExportOut(BaseModel):
    job_id: str
    target: str
    status: str
    files: dict[str, Any] = Field(default_factory=dict)
    html: str | None = None
    lint: dict[str, Any] | None = None
    mautic: dict[str, Any] | None = None
    message: str = ""


# ---------------------------------------------------------------- plugins

class PluginInstallIn(BaseModel):
    path: str | None = None                # 本地目录
    zip_path: str | None = None
    url: str | None = None
    activate: bool = True


class PluginOut(BaseModel):
    # 注意：不能设 from_attributes=True 直接从 ORM 读。
    # Plugin 的 DB 列是 runtime_state（避开 SQLAlchemy 声明式注册表的保留名 registry），
    # 若开启 from_attributes，Pydantic 会去读 obj.registry 拿到 declarative 的内部对象。
    # 这里改为显式装配，registry 字段由 plugins.py:plugin_dict() 填充。
    model_config = ConfigDict(from_attributes=False)

    id: str
    key: str
    name: str
    version: str
    kind: str
    description: str = ""
    author: str = ""
    status: str = "active"
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    registry: dict[str, Any] = Field(default_factory=dict)
    install_path: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_plugin(cls, p: Any) -> "PluginOut":
        from ..plugins.manager import plugin_dict
        return cls(**plugin_dict(p))


# ---------------------------------------------------------------- collaboration

class ReviewIn(BaseModel):
    to_status: str
    assignee_id: str | None = None
    reason: str = ""


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    content_id: str
    version_id: str | None
    from_status: str
    to_status: str
    reason: str
    state: str
    assignee_id: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


class CommentIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    block_id: str | None = None


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    content_id: str
    block_id: str | None
    body: str
    resolved: bool
    author_id: str | None
    author_name: str
    created_at: datetime


class LockIn(BaseModel):
    action: Literal["acquire", "release", "heartbeat"]
    ttl_seconds: int = 300


class ProjectIn(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    description: str = ""
    brand_tokens: dict[str, Any] = Field(default_factory=dict)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    key: str
    name: str
    description: str
    brand_tokens: dict[str, Any]
    created_at: datetime