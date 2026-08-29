"""
测试配置：用独立的 SQLite 测试库覆盖 get_db 依赖，不连真实 MySQL。
数据访问已统一为同步 DAO，测试同样走同步引擎。
"""
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app

# TestClient 启动会触发 lifespan → init_db()；测试库用 sqlite，模块级屏蔽真实建表（不连 MySQL）
import app.main as main_mod
main_mod.init_db = lambda: None

# 测试用独立 sqlite 文件，跑完不污染开发库
_TEST_DB = Path(__file__).resolve().parent.parent / "test_hina.db"
TEST_SYNC_DB_URL = f"sqlite:///{_TEST_DB}"

# 同步测试引擎 + session 工厂（REST 与 WebSocket 共用，同步 DAO 无循环绑定问题）
test_sync_engine = create_engine(TEST_SYNC_DB_URL, echo=False, future=True)
TestSyncSessionLocal = sessionmaker(bind=test_sync_engine, expire_on_commit=False)


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    """建表 + 测试结束后清理（不连真实 MySQL）"""
    Base.metadata.create_all(test_sync_engine)
    yield
    Base.metadata.drop_all(test_sync_engine)
    test_sync_engine.dispose()
    if _TEST_DB.exists():
        try:
            _TEST_DB.unlink()
        except (PermissionError, OSError):
            pass


def _override_get_db():
    """覆盖 REST 路由的 get_db 依赖（同步生成器）"""
    with TestSyncSessionLocal() as session:
        yield session


app.dependency_overrides[get_db] = _override_get_db


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
