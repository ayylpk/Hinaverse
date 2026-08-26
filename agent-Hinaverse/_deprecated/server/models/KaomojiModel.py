from sqlalchemy.orm import Session

from server.database import KaomojiEnity


class KaomojiRepository:
    """颜文字 —— 数据访问层"""

    def __init__(self, db: Session):
        self.db = db

    def add(self, content: str, kaomoji_type: str = "") -> KaomojiEnity | None:
        """新增颜文字，成功返回实体，失败返回 None"""
        try:
            kaomoji = KaomojiEnity(
                content=content,
                type=kaomoji_type,
            )
            self.db.add(kaomoji)
            self.db.commit()
            self.db.refresh(kaomoji)
            return kaomoji
        except Exception:
            self.db.rollback()
            return None

    def get_by_id(self, kaomoji_id: int) -> KaomojiEnity | None:
        """按 id 查询"""
        return self.db.query(KaomojiEnity).filter_by(id=kaomoji_id).first()

    def get_by_type(self, kaomoji_type: str, limit: int = 100) -> list[KaomojiEnity]:
        """按类型筛选"""
        return (
            self.db.query(KaomojiEnity)
            .filter_by(type=kaomoji_type)
            .limit(limit)
            .all()
        )

    def get_all(self, limit: int = 500) -> list[KaomojiEnity]:
        """获取全部"""
        return self.db.query(KaomojiEnity).limit(limit).all()

    def delete(self, kaomoji_id: int) -> bool:
        """删除颜文字，成功返回 True"""
        try:
            kaomoji = self.get_by_id(kaomoji_id)
            if kaomoji is None:
                return False
            self.db.delete(kaomoji)
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            return False
