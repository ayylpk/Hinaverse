# hina_memory 接入层单测：表结构 + SqlMemoryStore + service.remember 的端到端接线。
# 用 SQLite 跑（同一套 SQLAlchemy 语句），不需要 MySQL、不调 LLM（注入假摘要/假画像）。
# 运行：python -m pytest tests/test_hina_memory_service.py -q  或  python tests/test_hina_memory_service.py

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.hina_memory.models  # noqa: E402,F401  （注册 hm_* 表到 Base.metadata）
import app.models  # noqa: E402,F401  （hm_* 对 users.id 有外键，建表时需要 users 在 metadata 里）
from app.database import Base  # noqa: E402
from app.hina_memory import scheduler, service  # noqa: E402
from app.hina_memory.models import (  # noqa: E402
    HinaMemoryL1, HinaMemoryL2, HinaMemoryPortrait, HinaMemoryRaw, HinaMemoryState,
)

_DEFAULTS = {k: getattr(scheduler, k) for k in
             ("L1_CHUNK_CUMULATIVE", "POST_CAP_INTERVAL", "PORTRAIT_EVERY", "RAW_WINDOW")}


def setup_env(tmp_path, **thresholds):
    """建库 + 打薄阈值 + 让 service 用测试库。返回 session 工厂。"""
    engine = create_engine(f"sqlite:///{tmp_path / 'hm_service.db'}", future=True)
    Base.metadata.create_all(engine)
    for k in _DEFAULTS:
        setattr(scheduler, k, thresholds.get(k, _DEFAULTS[k]))
    factory = lambda: Session(engine, expire_on_commit=False)  # noqa: E731
    service._session = factory
    return factory


def teardown_env():
    for k, v in _DEFAULTS.items():
        setattr(scheduler, k, v)


def fake_summarize(entries):
    return f"摘要[{len(entries)}条]"


def fake_portrait(pending, old):
    return f"画像（第{'2' if old else '1'}版，基于 {len(pending)} 条 L2）"


def test_rows_and_roles(tmp_path):
    """一轮对话两条：user 与 ai 各一行，role 分清；未到档位不产生压缩。"""
    factory = setup_env(tmp_path, RAW_WINDOW=0)
    try:
        db = factory()
        service.remember(db, 7, "user", "我今天很累", summarize=fake_summarize, make_portrait=fake_portrait)
        service.remember(db, 7, "ai", "那早点休息", summarize=fake_summarize, make_portrait=fake_portrait)
        rows = db.execute(select(HinaMemoryRaw.role, HinaMemoryRaw.content).order_by(HinaMemoryRaw.seq)).all()
        assert [r[0] for r in rows] == ["user", "ai"]
        # 保护窗置 0 时首个档位（块 2）立刻触发 → 恰好 1 条 L1；默认窗 8 时这里会是 0 条
        assert len(db.execute(select(HinaMemoryL1)).scalars().all()) == 1
        state = db.get(HinaMemoryState, 7)
        assert state is not None and state.total_entries == 2
        db.close()
    finally:
        teardown_env()


def test_compression_and_portrait(tmp_path):
    """打薄阈值后：L1 触发 → L1 到顶 → L2 推送 → 画像生成并消费 L2。"""
    factory = setup_env(tmp_path, L1_CHUNK_CUMULATIVE=(2, 4), POST_CAP_INTERVAL=2,
                        PORTRAIT_EVERY=1, RAW_WINDOW=0)
    try:
        db = factory()
        for i in range(8):
            service.remember(db, 9, "user", f"第{i}条", summarize=fake_summarize, make_portrait=fake_portrait)
        l1 = db.execute(select(HinaMemoryL1.summary)).scalars().all()
        assert len(l1) == 2, f"期望 2 次 L1，实际 {len(l1)}：{l1}"
        assert len(db.execute(select(HinaMemoryL2)).scalars().all()) == 0  # 画像已消费
        portrait = service.portrait_of(9)
        assert portrait and "画像" in portrait
        assert db.get(HinaMemoryState, 9).l2_pushed >= 1
        db.close()
    finally:
        teardown_env()


def test_counters_persist_across_sessions(tmp_path):
    """换 session（≈换请求/重启）后压缩进度连续，不会从头再来。"""
    factory = setup_env(tmp_path, L1_CHUNK_CUMULATIVE=(2, 4), POST_CAP_INTERVAL=2,
                        PORTRAIT_EVERY=99, RAW_WINDOW=0)
    try:
        db1 = factory()
        for i in range(4):
            service.remember(db1, 11, "user", f"a{i}", summarize=fake_summarize, make_portrait=fake_portrait)
        db1.close()

        db2 = factory()
        state = db2.get(HinaMemoryState, 11)
        assert state.total_entries == 4 and state.l1_pushed == 2
        service.remember(db2, 11, "ai", "b", summarize=fake_summarize, make_portrait=fake_portrait)
        assert db2.get(HinaMemoryState, 11).total_entries == 5  # 接着数，不是重头
        db2.close()
    finally:
        teardown_env()


def test_portrait_isolated_per_user(tmp_path):
    """画像按用户隔离：A 的画像不会出现在 B 上。"""
    factory = setup_env(tmp_path, L1_CHUNK_CUMULATIVE=(2, 4), POST_CAP_INTERVAL=2,
                        PORTRAIT_EVERY=1, RAW_WINDOW=0)
    try:
        db = factory()
        for i in range(8):
            service.remember(db, 100, "user", f"甲{i}", summarize=fake_summarize, make_portrait=fake_portrait)
        assert service.portrait_of(100)
        assert service.portrait_of(200) is None
        assert db.execute(select(HinaMemoryPortrait)).scalars().all() != []
        db.close()
    finally:
        teardown_env()


def test_portrait_length_guard(monkeypatch):
    """画像超上限：先求模型压缩，仍超就按段落机械裁剪——绝不放超长画像进库。"""
    from app.hina_memory import llm

    long_portrait = "\n".join([
        "### 身份与生活",
        "用户是一名在互联网公司做后端的工程师，日常节奏是早十晚九，周末偶尔加班。" * 4,
        "### 性格与偏好",
        "性格偏内敛，说话不喜欢被打断，讨厌别人用「你应该」来给建议。" * 4,
        "### 近期状态",
        "最近在赶季度报告，压力偏大，睡眠推迟到凌晨一两点。" * 5,
        "### 陪伴要点",
        "别催他做决定，先接情绪；上次答应的书店话题可以再提。" * 4,
    ])

    class _FakeModel:
        def __init__(self, text):
            self.text = text

        def invoke(self, _prompt):
            return type("_Msg", (), {"content": self.text})()

    class _FakeModels:
        def __init__(self, text):
            self.reduce_model = _FakeModel(text)
            self.write_model = _FakeModel(text)

    # 模型两次都返回超长文本 → 必须落到机械裁剪
    monkeypatch.setattr(llm, "_agent_models", lambda: _FakeModels(long_portrait))

    assert len(long_portrait) > llm.PORTRAIT_MAX_CHARS
    out = llm.make_portrait(["一条 L2"], "旧画像")
    assert len(out) <= llm.PORTRAIT_MAX_CHARS, f"画像超上限：{len(out)} 字"
    assert out.startswith("### 身份与生活")  # 段落完整保留，不在句中截断

    # 正常长度则原样返回（不做多余加工）
    monkeypatch.setattr(llm, "_agent_models", lambda: _FakeModels("### 身份与生活\n后端工程师，早十晚九。"))
    short = llm.make_portrait(["一条 L2"], None)
    assert short == "### 身份与生活\n后端工程师，早十晚九。"


if __name__ == "__main__":
    import tempfile

    import pytest

    for name in ("test_rows_and_roles", "test_compression_and_portrait",
                 "test_counters_persist_across_sessions", "test_portrait_isolated_per_user"):
        globals()[name](Path(tempfile.mkdtemp()))
        print(f"  ok - {name}")
    mp = pytest.MonkeyPatch()
    test_portrait_length_guard(mp)
    mp.undo()
    print("  ok - test_portrait_length_guard")
    print("hina_memory service tests: all passed")
