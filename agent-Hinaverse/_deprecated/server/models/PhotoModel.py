from sqlalchemy.orm import Session
from datetime import datetime

from server.database import PhotoEnity


class PhotoRepository:
    """图片 —— 数据访问层"""

    def __init__(self, db: Session):
        self.db = db

    def add(self, path: str) -> PhotoEnity | None:
        """新增图片记录，时间自动生成，成功返回实体"""
        try:
            photo = PhotoEnity(
                path=path,
                time=int(datetime.now().timestamp() * 1000),
            )
            self.db.add(photo)
            self.db.commit()
            self.db.refresh(photo)
            return photo
        except Exception:
            self.db.rollback()
            return None

    def get_by_id(self, photo_id: int) -> PhotoEnity | None:
        """按 id 查询"""
        return self.db.query(PhotoEnity).filter_by(id=photo_id).first()

    def get_after(self, cursor_time: int | None = None, limit: int = 50) -> list[PhotoEnity]:
        """游标分页：获取 cursor_time 之前的图片（按时间降序）"""
        query = self.db.query(PhotoEnity).order_by(PhotoEnity.time.desc())
        if cursor_time is not None:
            query = query.filter(PhotoEnity.time < cursor_time)
        return query.limit(limit).all()

    def get_all(self, limit: int = 500) -> list[PhotoEnity]:
        """获取全部（按时间降序）"""
        return (
            self.db.query(PhotoEnity)
            .order_by(PhotoEnity.time.desc())
            .limit(limit)
            .all()
        )

    def delete(self, photo_id: int) -> bool:
        """删除图片记录，成功返回 True"""
        try:
            photo = self.get_by_id(photo_id)
            if photo is None:
                return False
            self.db.delete(photo)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False
