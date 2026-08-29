"""
FastAPI 应用入口：CORS、路由、WS 挂载、启动建表、日终定时任务。
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS
from app.database import init_db
from app.routers import auth, conversations, crisis, device, dev, dairy, sendMessage
from app.ws.ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# 日终总结触发时间（每天 23:00）
DAILY_SUMMARY_HOUR = 23
DAILY_SUMMARY_MINUTE = 0


async def _daily_summary_loop() -> None:
    """定时循环：每天 23:00 触发日终压缩（等不到就睡到那一刻）"""
    from app.services.daily_summary import run_daily_compress_for_all

    while True:
        now = datetime.now()
        target = now.replace(hour=DAILY_SUMMARY_HOUR, minute=DAILY_SUMMARY_MINUTE, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        # 后台异步执行，不阻塞定时循环
        asyncio.create_task(run_daily_compress_for_all())
        # 执行后立即睡到下一个 23:00
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动建表 + 起日终定时任务"""
    init_db()
    logging.getLogger(__name__).info("数据库表已就绪")
    daily_task = asyncio.create_task(_daily_summary_loop())
    logging.getLogger(__name__).info("日终定时任务已启动（每天 23:00）")
    yield
    daily_task.cancel()


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
app.include_router(sendMessage.router)
app.include_router(dairy.router)

# WebSocket 路由
app.include_router(ws_router)


@app.get("/")
async def root() -> dict:
    return {"service": "Hinaverse Backend", "status": "ok"}
