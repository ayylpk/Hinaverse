from sqlalchemy.orm import Session
from datetime import datetime

from server.database import DiaryOfMeEnity


class DiaryOfMeRepository:
    """我的日记 —— 数据访问层"""

    def __init__(self, db: Session):
        self.db = db

    def add(self, title: str, content: str, image_path: str = "") -> DiaryOfMeEnity | None:
        """新增日记，成功返回实体，失败返回 None"""
        try:
            diary = DiaryOfMeEnity(
                title=title,
                content=content,
                time=int(datetime.now().timestamp() * 1000),
                imagePath=image_path,
            )
            self.db.add(diary)
            self.db.commit()
            self.db.refresh(diary)
            return diary
        except Exception:
            self.db.rollback()
            return None

    def get_by_id(self, diary_id: int) -> DiaryOfMeEnity | None:
        """按 id 查询"""
        return self.db.query(DiaryOfMeEnity).filter_by(id=diary_id).first()

    def get_after(self, cursor_time: int | None = None, limit: int = 20) -> list[DiaryOfMeEnity]:
        """游标分页：获取 cursor_time 之前的日记（按时间降序）"""
        query = self.db.query(DiaryOfMeEnity).order_by(DiaryOfMeEnity.time.desc())
        if cursor_time is not None:
            query = query.filter(DiaryOfMeEnity.time < cursor_time)
        return query.limit(limit).all()

    def get_all(self, limit: int = 500) -> list[DiaryOfMeEnity]:
        """获取全部（按时间降序）"""
        return (
            self.db.query(DiaryOfMeEnity)
            .order_by(DiaryOfMeEnity.time.desc())
            .limit(limit)
            .all()
        )

    def update(
        self, diary_id: int,
        title: str | None = None,
        content: str | None = None,
        image_path: str | None = None,
    ) -> DiaryOfMeEnity | None:
        """更新日记字段，传 None 的不更新"""
        try:
            diary = self.get_by_id(diary_id)
            if diary is None:
                return None
            if title is not None:
                diary.title = title
            if content is not None:
                diary.content = content
            if image_path is not None:
                diary.imagePath = image_path
            self.db.commit()
            self.db.refresh(diary)
            return diary
        except Exception:
            self.db.rollback()
            return None

    def delete(self, diary_id: int) -> bool:
        """删除日记，成功返回 True"""
        try:
            diary = self.get_by_id(diary_id)
            if diary is None:
                return False
            self.db.delete(diary)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False
