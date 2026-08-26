from __future__ import annotations

from sqlalchemy.orm import Session
from typing import Optional

from server.models.DiaryOfMeModel import DiaryOfMeRepository
from server.result import Result


class DiaryOfMeService:
    """我的日记 —— 业务层"""

    def __init__(self, db: Session):
        self.repo = DiaryOfMeRepository(db)

    def create(self, title: str, content: str, image_path: str = "") -> Result[dict]:
        """新建日记"""
        if not title or not title.strip():
            return Result.error("标题不能为空")
        if len(title) > 20:
            return Result.error("标题不能超过20字")
        if not content or not content.strip():
            return Result.error("内容不能为空")

        entity = self.repo.add(title.strip(), content.strip(), image_path)
        if entity is None:
            return Result.error("写入失败")
        return Result.success(entity.to_dict(), "创建成功")

    def get(self, diary_id: int) -> Result[dict]:
        """按 id 查询"""
        entity = self.repo.get_by_id(diary_id)
        if entity is None:
            return Result.not_found(f"日记 id={diary_id} 不存在")
        return Result.success(entity.to_dict())

    def list(self, cursor: Optional[int] = None, limit: int = 20) -> Result[list[dict]]:
        """游标分页列表"""
        if limit < 1 or limit > 100:
            return Result.error("limit 范围: 1~100")
        entities = self.repo.get_after(cursor, limit)
        return Result.success([e.to_dict() for e in entities])

    def get_all(self, limit: int = 500) -> Result[list[dict]]:
        """获取全部"""
        entities = self.repo.get_all(limit)
        return Result.success([e.to_dict() for e in entities])

    def update(
        self, diary_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> Result[dict]:
        """更新日记，只更新传入的非 None 字段"""
        if title is not None and (not title.strip() or len(title) > 20):
            return Result.error("标题不能为空且不超过20字")

        entity = self.repo.update(
            diary_id,
            title=title.strip() if title else None,
            content=content.strip() if content else None,
            image_path=image_path,
        )
        if entity is None:
            return Result.not_found(f"日记 id={diary_id} 不存在或更新失败")
        return Result.success(entity.to_dict(), "更新成功")

    def delete(self, diary_id: int) -> Result[None]:
        """删除日记"""
        ok = self.repo.delete(diary_id)
        if not ok:
            return Result.not_found(f"日记 id={diary_id} 不存在或删除失败")
        return Result.success(None, "删除成功")
