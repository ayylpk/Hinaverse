from sqlalchemy.orm import Session
from datetime import datetime

# 从 table.py 导入 Entity，避免重复定义
from server.database import ChattingRecordsEnity


class ChatRepository:
    """数据访问层 —— 聊天记录 Mapper"""

    def __init__(self, db: Session):
        self.db = db

    # ── 增 ──
    def add(self, role: int, text: str) -> ChattingRecordsEnity | None:
        """新增聊天记录，成功返回实体，失败返回 None"""
        try:
            msg = ChattingRecordsEnity(
                role=role,
                text=text,
                time=int(datetime.now().timestamp() * 1000)
            )
            self.db.add(msg)
            self.db.commit()
            self.db.refresh(msg)
            return msg
        except Exception:
            self.db.rollback()
            return None

    # ── 查（单条） ──
    def get_by_id(self, msg_id: int) -> ChattingRecordsEnity | None:
        """按 id 查询单条记录"""
        return self.db.query(ChattingRecordsEnity).filter_by(id=msg_id).first()

    # ── 查（游标分页，降序） ──
    def get_after(
        self, cursor_time: int | None = None, limit: int = 50
    ) -> list[ChattingRecordsEnity]:
        """
        游标分页：获取 cursor_time **之前**的记录（按时间降序）。
        传 None 则取最新 limit 条。
        """
        query = self.db.query(ChattingRecordsEnity).order_by(
            ChattingRecordsEnity.time.desc()
        )
        if cursor_time is not None:
            query = query.filter(ChattingRecordsEnity.time < cursor_time)
        return query.limit(limit).all()

    # ── 查（全部，升序） ──
    def get_all(self, limit: int = 1000) -> list[ChattingRecordsEnity]:
        """按时间升序获取全部记录（上限 limit）"""
        query = self.db.query(ChattingRecordsEnity).order_by(
            ChattingRecordsEnity.time.asc()
        )
        return query.limit(limit).all()

    # ── 删 ──
    def delete(self, msg_id: int) -> bool:
        """删除一条记录，成功返回 True，不存在返回 False"""
        try:
            msg = self.get_by_id(msg_id)
            if msg is None:
                return False
            self.db.delete(msg)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False
