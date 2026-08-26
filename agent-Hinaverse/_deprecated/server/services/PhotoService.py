from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from server.models.PhotoModel import PhotoRepository
from server.result import Result


class PhotoService:
    """图片 —— 业务层"""

    def __init__(self, db: Session):
        self.repo = PhotoRepository(db)

    def add(self, path: str) -> Result[dict]:
        """新增图片记录"""
        if not path or not path.strip():
            return Result.error("路径不能为空")
        if len(path) > 250:
            return Result.error("路径不能超过250字符")

        entity = self.repo.add(path.strip())
        if entity is None:
            return Result.error("写入失败")
        return Result.success(entity.to_dict(), "添加成功")

    def get(self, photo_id: int) -> Result[dict]:
        """按 id 查询"""
        entity = self.repo.get_by_id(photo_id)
        if entity is None:
            return Result.not_found(f"图片 id={photo_id} 不存在")
        return Result.success(entity.to_dict())

    def list(self, cursor: Optional[int] = None, limit: int = 50) -> Result[list[dict]]:
        """游标分页列表"""
        if limit < 1 or limit > 200:
            return Result.error("limit 范围: 1~200")
        entities = self.repo.get_after(cursor, limit)
        return Result.success([e.to_dict() for e in entities])

    def get_all(self, limit: int = 500) -> Result[list[dict]]:
        """获取全部（按时间降序）"""
        entities = self.repo.get_all(limit)
        return Result.success([e.to_dict() for e in entities])

    def delete(self, photo_id: int) -> Result[None]:
        """删除图片记录"""
        ok = self.repo.delete(photo_id)
        if not ok:
            return Result.not_found(f"图片 id={photo_id} 不存在或删除失败")
        return Result.success(None, "删除成功")
