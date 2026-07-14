"""FastAPI 应用入口。

启动时初始化数据库并写入事件种子。挂载 REST 路由与 WebSocket 端点,
配置 CORS 允许前端 dev server 访问。
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.ws import ws_router
from app.core.config import settings
from app.core.db import init_db
from app.services import event_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        event_service.seed_events()
    except Exception:
        pass
    yield


app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(ws_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"app": settings.app_name, "version": settings.version, "docs": "/docs"}
