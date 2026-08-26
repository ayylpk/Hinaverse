"""
数据库：SQLAlchemy 2.0 异步 + aiosqlite。
统一通过 get_db 依赖获取 session，路由里用 async with 管理事务。
"""
from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import DB_URL

# echo=False 避免刷屏；future=True 启用 SQLAlchemy 2.0 风格
engine = create_async_engine(DB_URL, echo=False, future=True)

AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

# 同步引擎：仅供 WebSocket 长连接使用。
# 原因：WS 可能运行在与 REST 不同的事件循环里（如 TestClient 的 anyio 循环），
# 异步 engine 的连接池绑定单一循环，跨循环会抛错。SQLite 同步操作为亚毫秒级，
# 短暂阻塞事件循环可忽略，且天然跨循环/线程安全。
_sync_url = DB_URL.replace("sqlite+aiosqlite://", "sqlite://")
sync_engine = create_engine(_sync_url, echo=False, future=True)
SyncSessionLocal = sessionmaker(bind=sync_engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每个请求一个 session，结束自动关闭"""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """启动时建表（开发期直接 create_all，生产换 Alembic 迁移）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
