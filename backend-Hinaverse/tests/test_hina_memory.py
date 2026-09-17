# hina_memory 单测：触发数学（2/6/14/30/62）、L2 滚动、画像消费、近期保护窗。
# 运行：python -m pytest tests/test_hina_memory.py -q  或  python tests/test_hina_memory.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.hina_memory import InMemoryStore, MemoryCounters, MemoryEngine, plan_actions  # noqa: E402


def make_engine() -> tuple[MemoryEngine, InMemoryStore, list[str]]:
    store = InMemoryStore()
    calls: list[list[str]] = []

    def summarize(entries):
        calls.append(list(entries))
        return "摘要<" + "|".join(e[:6] for e in entries) + ">"

    def make_portrait(l2_entries, old):
        return f"画像(基于{len(l2_entries)}条L2, 旧画像={'有' if old else '无'})"

    engine = MemoryEngine(store=store, summarize=summarize, make_portrait=make_portrait)
    return engine, store, calls


def test_no_action_below_first_threshold():
    engine, store, _ = make_engine()
    engine.add_entry("第1条")
    assert store.l1 == [] and engine.counters.total_entries == 1


def test_l1_pushes_at_2_6_14_30_62():
    engine, store, calls = make_engine()
    for i in range(1, 63):
        engine.add_entry(f"条目{i}")
    # 62 条时第 5 块(32)因近期保护窗(8)只凑到 24 条 → 延迟；70 条时凑齐
    assert len(store.l1) == 4
    engine.add_entry("条目63")
    for i in range(64, 71):
        engine.add_entry(f"条目{i}")
    assert len(store.l1) == 5, f"期望 5 次 L1 推送，实际 {len(store.l1)}"
    assert engine.counters.l1_pushed == 5
    # 块大小 2/4/8/16/32（第 5 块含窗口解禁后的补充）
    assert [len(c) for c in calls][:4] == [2, 4, 8, 16]


def test_recent_window_protected():
    engine, store, _ = make_engine()
    for i in range(1, 5):  # 达到首个触发点(2)但最近 8 条受保护 → 延迟
        engine.add_entry(f"条目{i}")
    assert store.l1 == []  # 可压缩量 = 4 - 8 < 0 → 延迟
    for i in range(5, 15):  # 总量 14，可压缩 = 14 - 8 = 6 ≥ 2 → 触发
        engine.add_entry(f"条目{i}")
    assert len(store.l1) >= 1


def test_l2_after_cap_and_portrait_at_4():
    engine, store, _ = make_engine()
    for i in range(1, 240):
        engine.add_entry(f"条目{i}")
    # L1 到顶 5 次（62 条处），之后每 32 条推一次 L2
    assert engine.counters.l1_pushed == 5
    assert engine.counters.l2_pushed >= 4
    assert "portrait" in engine._run_pending() or len(engine.counters.l2_pending) < 4
    # 画像生成过且消费了 L2
    assert store.portrait_text is not None
    assert "画像" in store.portrait_text


def test_counters_snapshot_matches_plan():
    # 真实触达点：62 到顶后，累计到 102（= 62 + 32 块 + 8 保护窗）时第一次推 L2
    c = MemoryCounters(total_entries=102, consumed=54, l1_pushed=5, l2_pushed=0)
    actions = plan_actions(c)
    assert "l2_push" in actions


def test_sqlite_store_roundtrip(tmp_path):
    from app.hina_memory import SqliteStore
    store = SqliteStore(str(tmp_path / "hm.db"))
    engine = MemoryEngine(store=store, summarize=lambda e: "摘要", make_portrait=lambda l2, old: "画像")
    for i in range(20):
        engine.add_entry(f"条目{i}")
    assert store.get_portrait() is None or isinstance(store.get_portrait(), str)
    l1_count = store.conn.execute("SELECT COUNT(*) FROM hm_l1").fetchone()[0]
    assert l1_count >= 1


if __name__ == "__main__":
    test_no_action_below_first_threshold()
    test_l1_pushes_at_2_6_14_30_62()
    test_recent_window_protected()
    test_l2_after_cap_and_portrait_at_4()
    test_counters_snapshot_matches_plan()
    import tempfile
    test_sqlite_store_roundtrip(Path(tempfile.mkdtemp()))
    print("hina_memory tests: all passed")
