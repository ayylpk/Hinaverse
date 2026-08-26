from __future__ import annotations

from sqlalchemy.orm import Session
from typing import Optional

from server.models.ImRecordsModel import ImRecordsRepository
from server.result import Result


class ImRecordsService:
    """IM 聊天记录 —— 业务层"""

    def __init__(self, db: Session):
        self.repo = ImRecordsRepository(db)

    def send(self, role: int, text: str) -> Result[dict]:
        """写入一条 IM 消息"""
        if not text or not text.strip():
            return Result.error("消息不能为空")
        if role not in (0, 1):
            return Result.error("role 只能是 0 或 1")

        entity = self.repo.add(role, text.strip())
        if entity is None:
            return Result.error("写入失败")
        return Result.success(entity.to_dict(), "写入成功")

    def get(self, record_id: int) -> Result[dict]:
        """按 id 查询"""
        entity = self.repo.get_by_id(record_id)
        if entity is None:
            return Result.not_found(f"IM 消息 id={record_id} 不存在")
        return Result.success(entity.to_dict())

    def list(self, cursor: Optional[int] = None, limit: int = 50) -> Result[list[dict]]:
        """游标分页列表（按时间降序）"""
        if limit < 1 or limit > 200:
            return Result.error("limit 范围: 1~200")
        entities = self.repo.get_after(cursor, limit)
        return Result.success([e.to_dict() for e in entities])

    def get_all(self, limit: int = 1000) -> Result[list[dict]]:
        """获取全部（按时间升序）"""
        if limit < 1 or limit > 5000:
            return Result.error("limit 范围: 1~5000")
        entities = self.repo.get_all(limit)
        return Result.success([e.to_dict() for e in entities])

    def delete(self, record_id: int) -> Result[None]:
        """删除一条 IM 消息"""
        ok = self.repo.delete(record_id)
        if not ok:
            return Result.not_found(f"IM 消息 id={record_id} 不存在或删除失败")
        return Result.success(None, "删除成功")
