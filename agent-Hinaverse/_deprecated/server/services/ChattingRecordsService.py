from __future__ import annotations

from sqlalchemy.orm import Session
from typing import Optional

from server.models.ChattingRecordsModel import ChatRepository
from server.result import Result


class ChatService:
    """聊天业务层"""

    def __init__(self, db: Session):
        self.repo = ChatRepository(db)

    # ── 发送消息 ──
    def send_message(self, role: int, text: str) -> Result[dict]:
        """
        添加一条聊天消息。
        role: 0=日奈, 1=用户
        返回 Result，data 为消息字典
        """
        # 参数校验
        if not text or not text.strip():
            return Result.error("消息不能为空")
        if role not in (0, 1):
            return Result.error("role 只能是 0（日奈）或 1（用户）")

        entity = self.repo.add(role, text.strip())
        if entity is None:
            return Result.error("消息写入失败")

        return Result.success(entity.to_dict(), "发送成功")

    # ── 按 id 查询 ──
    def get_message(self, msg_id: int) -> Result[dict]:
        """按 id 查询单条消息"""
        entity = self.repo.get_by_id(msg_id)
        if entity is None:
            return Result.not_found(f"消息 id={msg_id} 不存在")
        return Result.success(entity.to_dict())

    # ── 游标分页查询 ──
    def get_history(
        self, cursor: Optional[int] = None, limit: int = 50
    ) -> Result[list[dict]]:
        """
        获取聊天历史（游标分页，按时间倒序）。
        cursor: 上一页最后一条记录的 time 值，传 None 取最新一页
        limit:  每页条数，默认 50，上限 200
        """
        if limit < 1 or limit > 200:
            return Result.error("limit 范围: 1~200")

        entities = self.repo.get_after(cursor, limit)
        data = [e.to_dict() for e in entities]
        return Result.success(data)

    # ── 获取全部 ──
    def get_all(self, limit: int = 1000) -> Result[list[dict]]:
        """获取全部消息（按时间升序），上限 5000"""
        if limit < 1 or limit > 5000:
            return Result.error("limit 范围: 1~5000")

        entities = self.repo.get_all(limit)
        data = [e.to_dict() for e in entities]
        return Result.success(data)

    # ── 删除消息 ──
    def delete_message(self, msg_id: int) -> Result[None]:
        """删除一条消息"""
        ok = self.repo.delete(msg_id)
        if not ok:
            return Result.not_found(f"消息 id={msg_id} 不存在或删除失败")
        return Result.success(None, "删除成功")
