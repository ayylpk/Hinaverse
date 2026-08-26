from sqlalchemy.orm import Session
from datetime import datetime

from server.database import ImRecordsEnity


class ImRecordsRepository:
    """IM 聊天记录 —— 数据访问层"""

    def __init__(self, db: Session):
        self.db = db

    def add(self, role: int, text: str) -> ImRecordsEnity | None:
        """新增一条 IM 消息，成功返回实体，失败返回 None"""
        try:
            record = ImRecordsEnity(
                role=role,
                text=text,
                time=int(datetime.now().timestamp() * 1000),
            )
            self.db.add(record)
            self.db.commit()
            self.db.refresh(record)
            return record
        except Exception:
            self.db.rollback()
            return None

    def get_by_id(self, record_id: int) -> ImRecordsEnity | None:
        """按 id 查询"""
        return self.db.query(ImRecordsEnity).filter_by(id=record_id).first()

    def get_after(self, cursor_time: int | None = None, limit: int = 50) -> list[ImRecordsEnity]:
        """游标分页：获取 cursor_time 之前的消息（按时间降序）"""
        query = self.db.query(ImRecordsEnity).order_by(ImRecordsEnity.time.desc())
        if cursor_time is not None:
            query = query.filter(ImRecordsEnity.time < cursor_time)
        return query.limit(limit).all()

    def get_all(self, limit: int = 1000) -> list[ImRecordsEnity]:
        """获取全部（按时间升序）"""
        return (
            self.db.query(ImRecordsEnity)
            .order_by(ImRecordsEnity.time.asc())
            .limit(limit)
            .all()
        )

    def delete(self, record_id: int) -> bool:
        """删除一条记录，成功返回 True"""
        try:
            record = self.get_by_id(record_id)
            if record is None:
                return False
            self.db.delete(record)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False
