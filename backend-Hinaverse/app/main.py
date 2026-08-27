"""
FastAPI 应用入口：CORS、路由、WS 挂载、启动建表。
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import init_db
from app.routers import auth, conversations, crisis, device, dev
from app.ws.ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时建表"""
    await init_db()
    logging.getLogger(__name__).info("数据库表已就绪")
    yield


app = FastAPI(title="Hinaverse Backend", version="0.1.0", lifespan=lifespan)

# CORS：开发期允许前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST 路由
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(device.router)
app.include_router(crisis.router)
app.include_router(dev.router)

# WebSocket 路由
app.include_router(ws_router)


@app.get("/")
async def root() -> dict:
    return {"service": "Hinaverse Backend", "status": "ok"}
