"""FastAPI 应用入口。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.v1 import api_router
from .blocks.registry import load_builtins
from .config import settings
from .db import SessionLocal, init_db
from .render import RENDERERS
from .render.generic import GenericRenderer

logger = logging.getLogger("campaign_edit")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DESCRIPTION = """
**Campaign Edit** —— 面向运营 / 前端 / 设计的内容创作后台。

核心链路：**自然语言意图 → 结构化内容计划 → 模板与组件推荐 → 块编辑器 → 交付产物**

三类内容共用一份 Block Schema，因此意图识别、模板、编辑器、渲染、导出、Mautic 投递
只有一条路径，不存在「邮件一套逻辑、表单一套逻辑、页面一套逻辑」的三倍维护成本。

* `POST /api/v1/intents` —— 意图识别（规则 + LLM 双通道，可直接落地创建）
* `GET  /api/v1/blocks` —— 组件注册表（编辑器左栏数据源）
* `POST /api/v1/contents/{id}/save` —— 保存新版本（带可投递性 lint 与乐观锁）
* `POST /api/v1/contents/{id}/export` —— 导出 HTML / bundle / Vite 脚手架 / Mautic
* `POST /api/v1/plugins/install` —— 安装组件包 / 主题包 / 意图规则 / MCP 插件
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_builtins()
    init_db()
    from .seed.bootstrap import run_bootstrap
    from .plugins.manager import load_builtin_demo_plugins, install_from_dir, sync_all
    with SessionLocal() as db:
        created = load_builtin_demo_plugins()
        for path in created:
            try:
                install_from_dir(db, path)
            except Exception as exc:
                logger.warning("示例插件安装跳过: %s", exc)
        run_bootstrap(db)
        res = sync_all(db)
        if res.get("errors"):
            logger.warning("插件同步告警: %s", res["errors"])
    logger.info("%s %s 已启动（env=%s, llm=%s）", settings.app_name, settings.app_version,
                settings.env, "on" if settings.llm_configured else "off")
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=DESCRIPTION,
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ValueError)
async def value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(api_router, prefix="/api/v1")


# 导出产物静态托管（方便前端"打开导出目录"）
export_dir = Path(settings.export_dir)
export_dir.mkdir(parents=True, exist_ok=True)
app.mount("/exports", StaticFiles(directory=str(export_dir)), name="exports")


@app.get("/", include_in_schema=False)
def root() -> dict:
    return {"name": settings.app_name, "version": settings.app_version,
            "docs": "/docs", "health": "/api/v1/health",
            "renderers": sorted(RENDERERS.keys()), "generic": GenericRenderer.kind}