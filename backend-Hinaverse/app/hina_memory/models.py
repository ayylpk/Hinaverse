# ============================================================
# models.py —— hina_memory 的表结构（与 users 同库，按 user_id 隔离）
#
#   hm_raw      L0 原文条目（只追加；consumed 标记是否已被压缩消费）
#   hm_l1       L1 摘要层
#   hm_l2       L2 深层摘要层（被画像消费后删除）
#   hm_portrait L3 画像（每用户一条，持续改写）
#   hm_state    调度计数器快照（l2_pushed 无法从行数推导，必须落库）
#
# 表由 app.main 启动时的 Base.metadata.create_all 自动创建。
# ============================================================

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HinaMemoryRaw(Base):
    """L0 原文条目（角色 + 内容），永不压缩、永不删除——细节的真相源。"""
    __tablename__ = "hm_raw"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)  # user | ai（画像必须分清谁说的）
    content: Mapped[str] = mapped_column(Text, nullable=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class HinaMemoryL1(Base):
    """L1 摘要层：一批原文 → 一条摘要。"""
    __tablename__ = "hm_l1"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class HinaMemoryL2(Base):
    """L2 深层摘要层：L1 到顶后按间隔推入；被画像消费即删除（画像的输入）。"""
    __tablename__ = "hm_l2"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)


class HinaMemoryPortrait(Base):
    """L3 画像：每用户一条，每次刷新整体改写（不是追加）。"""
    __tablename__ = "hm_portrait"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class HinaMemoryState(Base):
    """调度计数器快照（每用户一条）：进程重启/多次请求之间保持压缩进度连续。"""
    __tablename__ = "hm_state"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), primary_key=True)
    total_entries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    l1_pushed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    l2_pushed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
