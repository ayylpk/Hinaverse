from __future__ import annotations

from sqlalchemy.orm import Session

from server.models.KaomojiModel import KaomojiRepository
from server.result import Result


class KaomojiService:
    """颜文字 —— 业务层"""

    def __init__(self, db: Session):
        self.repo = KaomojiRepository(db)

    def add(self, content: str, kaomoji_type: str = "") -> Result[dict]:
        """新增颜文字"""
        if not content or not content.strip():
            return Result.error("颜文字内容不能为空")
        if len(content) > 30:
            return Result.error("颜文字不能超过30字符")

        entity = self.repo.add(content.strip(), kaomoji_type)
        if entity is None:
            return Result.error("写入失败")
        return Result.success(entity.to_dict(), "添加成功")

    def get(self, kaomoji_id: int) -> Result[dict]:
        """按 id 查询"""
        entity = self.repo.get_by_id(kaomoji_id)
        if entity is None:
            return Result.not_found(f"颜文字 id={kaomoji_id} 不存在")
        return Result.success(entity.to_dict())

    def list_by_type(self, kaomoji_type: str, limit: int = 100) -> Result[list[dict]]:
        """按类型筛选"""
        entities = self.repo.get_by_type(kaomoji_type, limit)
        return Result.success([e.to_dict() for e in entities])

    def get_all(self, limit: int = 500) -> Result[list[dict]]:
        """获取全部"""
        entities = self.repo.get_all(limit)
        return Result.success([e.to_dict() for e in entities])

    def delete(self, kaomoji_id: int) -> Result[None]:
        """删除颜文字"""
        ok = self.repo.delete(kaomoji_id)
        if not ok:
            return Result.not_found(f"颜文字 id={kaomoji_id} 不存在或删除失败")
        return Result.success(None, "删除成功")
