"""应用配置：全部可通过环境变量覆盖，默认零依赖可跑。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_bool(key: str, default: bool = False) -> bool:
    raw = _env(key)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _env_list(key: str, default: str = "") -> list[str]:
    raw = _env(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Campaign Edit"
    app_version: str = "0.1.0"
    env: str = "development"
    debug: bool = True

    # --- 存储 ---
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'campaign_edit.db').as_posix()}"
    db_echo: bool = False

    # --- 鉴权 ---
    jwt_secret: str = "change-me-in-production"
    jwt_ttl_seconds: int = 60 * 60 * 12
    auth_disabled: bool = False  # 本地演示可置 true，跳过鉴权
    bootstrap_admin_email: str = "admin@csts.dev"
    bootstrap_admin_password: str = "admin12345"
    bootstrap_admin_name: str = "小腾"

    # --- LLM（意图识别第二通道）---
    llm_enabled: bool = True
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_timeout_seconds: int = 30
    llm_temperature: float = 0.1
    llm_max_tokens: int = 1600

    # --- 意图引擎 ---
    intent_rule_weight: float = 0.45     # 规则通道置信度基线
    intent_llm_weight: float = 0.55      # LLM 通道权重
    intent_min_confidence: float = 0.35  # 低于该值走人工确认
    intent_auto_template_score: float = 0.55

    # --- 导出 ---
    export_dir: str = str(BASE_DIR / "data" / "exports")
    export_base_url: str = "http://localhost:8000"
    asset_dir: str = str(BASE_DIR / "data" / "assets")

    # --- 插件 ---
    plugin_dir: str = str(BASE_DIR / "plugins")
    plugin_allow_remote_install: bool = False  # 远程安装默认关闭（安全）
    plugin_registry_url: str = ""

    # --- Mautic ---
    mautic_base_url: str = ""
    mautic_username: str = ""
    mautic_password: str = ""
    mautic_api_enabled: bool = False

    # --- CORS ---
    cors_origins: list[str] = field(default_factory=lambda: [
        "http://localhost:5173", "http://127.0.0.1:5173",
    ])

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_api_key and self.llm_base_url)

    @property
    def mautic_configured(self) -> bool:
        return bool(self.mautic_api_enabled and self.mautic_base_url and self.mautic_username)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    return Settings(
        app_name=_env("APP_NAME", s.app_name),
        app_version=_env("APP_VERSION", s.app_version),
        env=_env("APP_ENV", s.env),
        debug=_env_bool("APP_DEBUG", s.debug),
        database_url=_env("DATABASE_URL", s.database_url),
        db_echo=_env_bool("DB_ECHO", s.db_echo),
        jwt_secret=_env("JWT_SECRET", s.jwt_secret),
        jwt_ttl_seconds=_env_int("JWT_TTL_SECONDS", s.jwt_ttl_seconds),
        auth_disabled=_env_bool("AUTH_DISABLED", s.auth_disabled),
        bootstrap_admin_email=_env("BOOTSTRAP_ADMIN_EMAIL", s.bootstrap_admin_email),
        bootstrap_admin_password=_env("BOOTSTRAP_ADMIN_PASSWORD", s.bootstrap_admin_password),
        bootstrap_admin_name=_env("BOOTSTRAP_ADMIN_NAME", s.bootstrap_admin_name),
        llm_enabled=_env_bool("LLM_ENABLED", s.llm_enabled),
        llm_base_url=_env("LLM_BASE_URL", s.llm_base_url),
        llm_model=_env("LLM_MODEL", s.llm_model),
        llm_api_key=_env("LLM_API_KEY", s.llm_api_key),
        llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", s.llm_timeout_seconds),
        llm_temperature=float(_env("LLM_TEMPERATURE", str(s.llm_temperature))),
        llm_max_tokens=_env_int("LLM_MAX_TOKENS", s.llm_max_tokens),
        intent_rule_weight=float(_env("INTENT_RULE_WEIGHT", str(s.intent_rule_weight))),
        intent_llm_weight=float(_env("INTENT_LLM_WEIGHT", str(s.intent_llm_weight))),
        intent_min_confidence=float(_env("INTENT_MIN_CONFIDENCE", str(s.intent_min_confidence))),
        intent_auto_template_score=float(
            _env("INTENT_AUTO_TEMPLATE_SCORE", str(s.intent_auto_template_score))
        ),
        export_dir=_env("EXPORT_DIR", s.export_dir),
        export_base_url=_env("EXPORT_BASE_URL", s.export_base_url),
        asset_dir=_env("ASSET_DIR", s.asset_dir),
        plugin_dir=_env("PLUGIN_DIR", s.plugin_dir),
        plugin_allow_remote_install=_env_bool("PLUGIN_ALLOW_REMOTE_INSTALL", False),
        plugin_registry_url=_env("PLUGIN_REGISTRY_URL", ""),
        mautic_base_url=_env("MAUTIC_BASE_URL", s.mautic_base_url),
        mautic_username=_env("MAUTIC_USERNAME", s.mautic_username),
        mautic_password=_env("MAUTIC_PASSWORD", s.mautic_password),
        mautic_api_enabled=_env_bool("MAUTIC_API_ENABLED", False),
        cors_origins=_env_list("CORS_ORIGINS", ",".join(s.cors_origins)),
    )


settings = get_settings()