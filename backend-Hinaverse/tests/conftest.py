"""
测试配置：统一走本机 MySQL 的独立测试库 hinaverse_test（需预先建库），不连开发库 hinaverse。
凭据复用 app.config 的 MYSQL_* 环境变量；URL 整体可用 HINA_TEST_DB_URL 覆盖。
数据访问已统一为同步 DAO，测试同样走同步引擎。
"""
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import MYSQL_HOST, MYSQL_PASSWORD, MYSQL_PORT, MYSQL_USER
from app.database import Base, get_db
from app.main import app

# TestClient 启动会触发 lifespan → init_db()；测试库用 sqlite，模块级屏蔽真实建表（不连 MySQL）
import app.main as main_mod
main_mod.init_db = lambda: None

TEST_SYNC_DB_URL = os.getenv(
    "HINA_TEST_DB_URL",
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/hinaverse_test?charset=utf8mb4",
)

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


@pytest.fixture
def clean_users():
    """登记要清理的测试用户名，测试结束后从测试库删除（防用例间数据污染）"""
    from sqlalchemy import select

    from app.models import User

    created: list[str] = []

    def _track(username: str) -> None:
        created.append(username)

    yield _track

    for name in created:
        with TestSyncSessionLocal() as s:
            u = s.execute(select(User).where(User.username == name)).scalar_one_or_none()
            if u is not None:
                s.delete(u)
                s.commit()


@pytest_asyncio.fixture
async def client():
    """httpx 异步测试客户端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
