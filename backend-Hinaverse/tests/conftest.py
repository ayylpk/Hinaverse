"""
测试配置：用独立的测试数据库覆盖 get_db 依赖。
"""
import asyncio
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# 测试用独立 sqlite 文件，跑完不污染开发库
_TEST_DB = Path(__file__).resolve().parent.parent / "test_hina.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{_TEST_DB}"
# 同步版 URL（WebSocket 路径用）
TEST_SYNC_DB_URL = f"sqlite:///{_TEST_DB}"

# 异步测试引擎 + session 工厂
test_engine = create_async_engine(TEST_DB_URL, echo=False, future=True)
TestSessionLocal = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

# 同步测试引擎 + session 工厂（供 WebSocket 路径使用）
test_sync_engine = create_engine(TEST_SYNC_DB_URL, echo=False, future=True)
TestSyncSessionLocal = sessionmaker(bind=test_sync_engine, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    """pytest-asyncio 需要事件循环 fixture"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    """建表 + 测试结束后清理"""
    # 异步引擎建表（同步引擎指向同一文件，可见相同表结构）
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    # 关闭引擎释放文件句柄，避免 Windows 下删文件失败
    await test_engine.dispose()
    test_sync_engine.dispose()
    if _TEST_DB.exists():
        try:
            _TEST_DB.unlink()
        except PermissionError:
            pass


async def _override_get_db():
    async with TestSessionLocal() as session:
        yield session


# 覆盖 REST 路由的 get_db 依赖
app.dependency_overrides[get_db] = _override_get_db


# 覆盖 WebSocket 路径的同步 session 工厂
@pytest.fixture(autouse=True)
def _patch_ws_session(monkeypatch):
    """把 ws 模块里的 SyncSessionLocal 替换为测试库的同步工厂"""
    import app.ws.ws as ws_mod
    monkeypatch.setattr(ws_mod, "SyncSessionLocal", TestSyncSessionLocal)


@pytest_asyncio.fixture
async def client():
    """httpx 异步测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
