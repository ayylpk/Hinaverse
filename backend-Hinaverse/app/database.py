"""
数据库：统一同步访问（SQLAlchemy 2.0 + PyMySQL 连 MySQL）。

为什么全项目统一同步：
    1. REST 路由用同步 def（FastAPI 自动放线程池执行），WebSocket 直接同步调用，
       数据访问只有一套代码、一个引擎，不再有 async/sync 双轨混乱。
    2. WebSocket 长连接天然跨线程，同步 session 无事件循环绑定问题（MySQL 异步驱动
       asyncmy 的连接绑定循环，跨循环会炸——这是原双引擎设计的根源，现已消除）。
    3. 简单 CRUD 毫秒级，线程池执行不阻塞事件循环，对当前规模足够。

所有业务查询统一走 app/repositories/（DAO 层），本文件只负责引擎与 session 工厂。
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DB_URL

# echo=False 避免刷屏；pool_pre_ping 保证 MySQL 断连后自动重连
engine = create_engine(DB_URL, echo=False, future=True, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)

# 兼容别名：早期代码（ws.py 等）引用 SyncSessionLocal，统一后仍可用
SyncSessionLocal = SessionLocal


class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 session，结束自动关闭（同步，FastAPI 放线程池执行）"""
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    """
    启动时建表（开发期直接 create_all，生产换 Alembic 迁移）。
    注意：只建表不建库，MySQL 库需预先创建（CREATE DATABASE hinaverse CHARACTER SET utf8mb4）。
    """
    Base.metadata.create_all(engine)
