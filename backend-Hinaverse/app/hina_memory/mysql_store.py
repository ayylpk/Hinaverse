# ============================================================
# mysql_store.py —— MemoryStore 的 SQLAlchemy 实现（与 users 同库）
#
#   一个 store 实例绑定「一个 db session + 一个 user_id」，方法语义见 engine.MemoryStore。
#   计数器（total_entries / consumed / l1_pushed / l2_pushed）落 hm_state，
#   l2_pending 由 hm_l2 行推导——画像消费时删行，所以 pending 不必另存。
# ============================================================

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .models import (
    HinaMemoryL1, HinaMemoryL2, HinaMemoryPortrait, HinaMemoryRaw, HinaMemoryState,
)
from .scheduler import MemoryCounters


class SqlMemoryStore:
    """MySQL/SQLite 通用（同一套 SQLAlchemy 语句，测试用 sqlite 也跑得通）。"""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._speaker = "entry"   # 通过 speaker() 设置后再 add_entry

    def speaker(self, role: str) -> "SqlMemoryStore":
        """声明接下来 append_raw 的发言者（user / ai）。越短越好，别让调用方记顺序。"""
        self._speaker = role
        return self

    # ── L0 原文 ──
    def append_raw(self, content: str) -> int:
        row = HinaMemoryRaw(user_id=self.user_id, role=self._speaker, content=content)
        self.db.add(row)
        self.db.flush()
        return row.seq

    def take_unconsumed(self, count: int) -> list[str]:
        rows = self.db.execute(
            select(HinaMemoryRaw.role, HinaMemoryRaw.content)
            .where(HinaMemoryRaw.user_id == self.user_id, HinaMemoryRaw.consumed.is_(False))
            .order_by(HinaMemoryRaw.seq)
            .limit(count)
        ).all()
        # 摘要必须分清谁说的：出口统一带上发言者标签
        return [f"{'用户' if role == 'user' else '日奈'}：{content}" for role, content in rows]

    def mark_consumed(self, count: int) -> None:
        seqs = self.db.execute(
            select(HinaMemoryRaw.seq)
            .where(HinaMemoryRaw.user_id == self.user_id, HinaMemoryRaw.consumed.is_(False))
            .order_by(HinaMemoryRaw.seq)
            .limit(count)
        ).scalars().all()
        if seqs:
            self.db.execute(
                HinaMemoryRaw.__table__.update()
                .where(HinaMemoryRaw.seq.in_(seqs))
                .values(consumed=True)
            )

    # ── L1 / L2 ──
    def append_l1(self, summary: str) -> None:
        self.db.add(HinaMemoryL1(user_id=self.user_id, summary=summary))

    def append_l2(self, summary: str) -> None:
        self.db.add(HinaMemoryL2(user_id=self.user_id, summary=summary))

    def l2_pending(self) -> list[str]:
        rows = self.db.execute(
            select(HinaMemoryL2.summary)
            .where(HinaMemoryL2.user_id == self.user_id)
            .order_by(HinaMemoryL2.seq)
        ).scalars().all()
        return list(rows)

    def clear_l2(self) -> None:
        self.db.execute(delete(HinaMemoryL2).where(HinaMemoryL2.user_id == self.user_id))

    # ── L3 画像 ──
    def get_portrait(self) -> str | None:
        return self.db.execute(
            select(HinaMemoryPortrait.text).where(HinaMemoryPortrait.user_id == self.user_id)
        ).scalar_one_or_none()

    def set_portrait(self, text: str) -> None:
        row = self.db.get(HinaMemoryPortrait, self.user_id)
        if row is None:
            self.db.add(HinaMemoryPortrait(user_id=self.user_id, text=text))
        else:
            row.text = text

    # ── 调度计数器 ──
    def load_counters(self) -> MemoryCounters:
        state = self.db.get(HinaMemoryState, self.user_id)
        if state is None:
            return MemoryCounters()
        return MemoryCounters(
            total_entries=state.total_entries,
            consumed=state.consumed,
            l1_pushed=state.l1_pushed,
            l2_pushed=state.l2_pushed,
            l2_pending=self.l2_pending(),
        )

    def save_counters(self, c: MemoryCounters) -> None:
        state = self.db.get(HinaMemoryState, self.user_id)
        if state is None:
            state = HinaMemoryState(user_id=self.user_id)
            self.db.add(state)
        state.total_entries = c.total_entries
        state.consumed = c.consumed
        state.l1_pushed = c.l1_pushed
        state.l2_pushed = c.l2_pushed


# ── 只读辅助（供 service 层做展示/诊断，不走 engine）──

def count_raw(db: Session, user_id: int) -> int:
    return db.execute(
        select(func.count()).select_from(HinaMemoryRaw).where(HinaMemoryRaw.user_id == user_id)
    ).scalar_one()
