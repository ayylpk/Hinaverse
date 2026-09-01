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
from app.routers import auth, checkin, conversations, crisis, device, dev, dairy, sendMessage
from app.services.inactive_memory import inactive_scan_loop
from app.ws.ws import router as ws_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# 日终总结触发时间（每天 24:00；23 点历史原因已废弃，24 点更贴合"清一天"语义）
DAILY_SUMMARY_HOUR = 0
DAILY_SUMMARY_MINUTE = 0


async def _daily_summary_loop() -> None:
    """定时循环：每天 24:00 触发日终压缩（等不到就睡到那一刻）"""
    from app.services.daily_summary import run_daily_compress_for_all

    while True:
        now = datetime.now()
        target = now.replace(hour=DAILY_SUMMARY_HOUR, minute=DAILY_SUMMARY_MINUTE, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())
        # 后台异步执行，不阻塞定时循环
        asyncio.create_task(run_daily_compress_for_all())
        # 执行后立即睡到下一个 24:00
        await asyncio.sleep(60)


# ── 极光 reg_id 查询回调：喂给 OutboundHub 降级前注入（Hub 不碰 DB，9/1 断链修复）──


def _lookup_user_reg_id(user_id: int) -> str:
    """按用户查 reg_id，查不到/未注册返回空串（push_offline 会跳过）。同步函数，Hub 会丢线程池调用。"""
    from app.database import SyncSessionLocal
    from app.repositories import user_repo

    with SyncSessionLocal() as db:
        user = user_repo.get_by_id(db, user_id)
        return (user.reg_id or "") if user else ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动建表 + 日终定时任务 + 离开落盘扫描"""
    init_db()
    logging.getLogger(__name__).info("数据库表已就绪")
    from app.ws.Hub import outbound_hub

    outbound_hub.register_reg_id_lookup(_lookup_user_reg_id)
    logging.getLogger(__name__).info("极光 reg_id 查询回调已挂 OutboundHub")
    daily_task = asyncio.create_task(_daily_summary_loop())
    logging.getLogger(__name__).info("日终定时任务已启动（每天 24:00）")
    inactive_task = asyncio.create_task(inactive_scan_loop())
    logging.getLogger(__name__).info("离开落盘扫描已启动（每 10 分钟扫描离线超时用户）")
    yield
    daily_task.cancel()
    inactive_task.cancel()


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
app.include_router(checkin.router)

# WebSocket 路由
app.include_router(ws_router)


@app.get("/")
async def root() -> dict:
    return {"service": "Hinaverse Backend", "status": "ok"}
