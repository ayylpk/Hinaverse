# ============================================================
# engine.py —— 记忆引擎：接收原文条目 → 按调度执行压缩 → 维护画像
#
#   Summarizer / PortraitMaker 由调用方注入（生产环境接 LLM，测试接假函数）。
#   Store 抽象存储：内存实现用于测试，SQLAlchemy 实现由 Hinaverse 侧按需接。
# ============================================================

from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .scheduler import (
    ACTION_DEFERRED, ACTION_L1, ACTION_L2, ACTION_PORTRAIT,
    MemoryCounters, plan_actions,
)


class MemoryStore(Protocol):
    """存储协议：调用方用 MySQL/SQLite 实现即可（方法语义见各签名）。"""

    def append_raw(self, content: str) -> int: ...          # 返回该条目序号
    def mark_consumed(self, count: int) -> None: ...        # 最旧的 count 条标记已压缩
    def take_unconsumed(self, count: int) -> list[str]: ... # 取最旧的 count 条未压缩原文
    def append_l1(self, summary: str) -> None: ...
    def append_l2(self, summary: str) -> None: ...
    def l2_pending(self) -> list[str]: ...
    def clear_l2(self) -> None: ...
    def get_portrait(self) -> str | None: ...
    def set_portrait(self, text: str) -> None: ...


@dataclass
class MemoryEngine:
    store: MemoryStore
    summarize: Callable[[Sequence[str]], str]        # 一批原文 → 一条摘要
    make_portrait: Callable[[Sequence[str], str | None], str]  # (L2 未消费条目, 旧画像) → 新画像
    counters: MemoryCounters = field(default_factory=MemoryCounters)
    on_event: Callable[[str, dict], None] | None = None  # 观测钩子（日志/上报用）

    def _emit(self, action: str, detail: dict) -> None:
        if self.on_event:
            self.on_event(action, detail)

    def add_entry(self, content: str) -> list[str]:
        """追加一条原文，执行所有由此触发的压缩动作，返回执行过的动作列表。"""
        self.store.append_raw(content)
        self.counters.total_entries += 1
        return self._run_pending()

    def _run_pending(self) -> list[str]:
        executed: list[str] = []
        while True:
            actions = plan_actions(self.counters)
            if not actions or ACTION_DEFERRED in actions and len(actions) == 1:
                break
            acted = False
            for a in actions:
                if a == ACTION_L1:
                    chunk = self._chunk_size_for_next_l1()
                    entries = self.store.take_unconsumed(chunk)
                    self.store.append_l1(self.summarize(entries))
                    self.store.mark_consumed(len(entries))
                    self.counters.consumed += len(entries)
                    self.counters.l1_pushed += 1
                elif a == ACTION_L2:
                    entries = self.store.take_unconsumed(32)
                    summary = self.summarize(entries)
                    self.store.append_l2(summary)
                    self.store.mark_consumed(len(entries))
                    self.counters.consumed += len(entries)
                    self.counters.l2_pushed += 1
                    self.counters.l2_pending.append(summary)  # 同步计数，否则画像永不触发
                elif a == ACTION_PORTRAIT:
                    pending = self.store.l2_pending()
                    portrait = self.make_portrait(pending, self.store.get_portrait())
                    self.store.set_portrait(portrait)
                    self.store.clear_l2()
                    self.counters.l2_pending = []
                else:
                    continue
                executed.append(a)
                self._emit(a, {})
                acted = True
            if not acted:
                break
        return executed

    def _chunk_size_for_next_l1(self) -> int:
        from .scheduler import L1_CHUNK_CUMULATIVE
        pushed = self.counters.l1_pushed
        prev = L1_CHUNK_CUMULATIVE[pushed - 1] if pushed > 0 else 0
        return L1_CHUNK_CUMULATIVE[pushed] - prev

    def portrait(self) -> str | None:
        return self.store.get_portrait()
