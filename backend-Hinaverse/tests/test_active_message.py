"""
主动关心消息链路测试（阶段 4：存数据库 + 统一扫描触发）

全假件零网络：假 push（outbound_hub.push monkeypatch）+ 假 LLM（spontaneous_model 替身），
真连 hinaverse_test 库（沿用 conftest 的 MySQL 测试库体系）。
覆盖：repo 队列操作 / accept 政策校验 / scan 三闸门与状态机 / 节点解析 / 收尾流接线。
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

import app.services.active_message as am
from app.models import Conversation, CrisisEvent, Message, SendMessage, User
from app.repositories import send_message_repo
from tests.conftest import TestSyncSessionLocal


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch):
    """active_message 的库会话指到测试库（conftest 只帮 ws 打了这个补丁）"""
    monkeypatch.setattr(am, "SyncSessionLocal", TestSyncSessionLocal)


@pytest.fixture
def env():
    """造一个带会话的测试用户，用例结束把牵连的表清干净"""
    with TestSyncSessionLocal() as db:
        u = User(username="active_u", hashed_password="x", nickname="主动君", role="user")
        db.add(u)
        db.commit()
        db.refresh(u)
        conv = Conversation(user_id=u.id, title="测试会话")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        uid, cid = u.id, conv.id
    yield uid, cid
    # 逐表按各自的关联列清理（Message 只有 conversation_id，别拿 user_id 套它）
    with TestSyncSessionLocal() as db:
        db.execute(delete(Message).where(Message.conversation_id == cid))
        db.execute(delete(CrisisEvent).where(CrisisEvent.user_id == uid))
        db.execute(delete(SendMessage).where(SendMessage.user_id == uid))
        db.execute(delete(Conversation).where(Conversation.id == cid))
        db.execute(delete(User).where(User.id == uid))
        db.commit()


def _make_push_ok(monkeypatch, ok=True):
    """把 outbound_hub.push 换成假件，记录调用；返回 calls 列表"""
    from app.ws.Hub import outbound_hub

    calls: list[dict] = []

    async def fake_push(user_id, msg):
        calls.append({"user_id": user_id, "msg": msg})
        return ok

    monkeypatch.setattr(outbound_hub, "push", fake_push)
    return calls


# ═══════════════════════════════════════════════════════════════════
# repo：队列生命周期
# ═══════════════════════════════════════════════════════════════════

def test_repo_lifecycle(env):
    uid, _ = env
    now = datetime.now()
    with TestSyncSessionLocal() as db:
        m1 = send_message_repo.create_pending(db, uid, "关心一", now - timedelta(minutes=5))
        m2 = send_message_repo.create_pending(db, uid, "关心二", now + timedelta(days=1))

        # 到点的只有 m1；升序
        due = send_message_repo.fetch_due(db, now)
        assert [m.id for m in due if m.user_id == uid] == [m1.id]

        # 撤销：两条都变 cancelled，返回条数
        assert send_message_repo.cancel_pending(db, uid) == 2
        db.refresh(m1); db.refresh(m2)
        assert m1.status == "cancelled" and m2.status == "cancelled"

        # 状态机：sent / expired / fail 三次烧成 cancelled
        m3 = send_message_repo.create_pending(db, uid, "关心三", now)
        send_message_repo.mark_sent(db, m3)
        assert m3.status == "sent"

        m4 = send_message_repo.create_pending(db, uid, "关心四", now)
        send_message_repo.mark_expired(db, m4)
        assert m4.status == "expired"

        m5 = send_message_repo.create_pending(db, uid, "关心五", now)
        for i in range(send_message_repo.MAX_FAIL - 1):
            send_message_repo.bump_fail(db, m5)
            assert m5.status == "pending"
        send_message_repo.bump_fail(db, m5)
        assert m5.status == "cancelled" and m5.fail_count == send_message_repo.MAX_FAIL


# ═══════════════════════════════════════════════════════════════════
# accept_spontaneous：政策校验（不信 LLM 自律）
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def always_open_window(monkeypatch):
    """把送达窗口撑成全天，让校验用例不受运行时刻影响（静默逻辑单测另开）"""
    monkeypatch.setattr(am, "QUIET_START", 0)
    monkeypatch.setattr(am, "QUIET_END", 24)


def test_accept_valid_and_replaces_old(env, always_open_window):
    uid, _ = env
    good = {"content": "上午说的面试，后来怎么样了？",
            "time": (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")}
    with TestSyncSessionLocal() as db:
        first_pending = send_message_repo.create_pending(db, uid, "旧的", datetime.now())
        old_id = first_pending.id

    mid = am.accept_spontaneous(uid, good)
    assert mid is not None
    with TestSyncSessionLocal() as db:
        # 旧对象属于上一个已关闭会话，按 id 重查（refresh 跨会话不可用）
        old = db.get(SendMessage, old_id)
        assert old.status == "cancelled"                     # 至多一条：旧的被顶掉
        new = db.get(SendMessage, mid)
        assert new.status == "pending" and new.content == good["content"]


@pytest.mark.parametrize("payload", [
    {"content": "", "time": "2026-09-02 15:00"},                                  # 空正文
    {"content": "话" * 501, "time": "2026-09-02 15:00"},                          # 超长
    {"content": "太贴脸了", "time": (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")},   # 不到 30 分钟
    {"content": "太晚了", "time": (datetime.now() + timedelta(hours=100)).strftime("%Y-%m-%d %H:%M")},      # 超 48 小时
    {"content": "时间坏了", "time": "明天下午"},                                   # 格式非法
])
def test_accept_rejects(env, always_open_window, payload):
    uid, _ = env
    assert am.accept_spontaneous(uid, payload) is None
    with TestSyncSessionLocal() as db:
        left = db.query(SendMessage).filter_by(user_id=uid).all()
        assert left == []


def test_accept_rejects_quiet_hours(env):
    """深夜送达的关心：政策直接拒收（哪怕 LLM 定时定歪了）"""
    uid, _ = env
    monkey_target = (datetime.now() + timedelta(hours=2)).replace(hour=3, minute=0)
    payload = {"content": "夜半关心", "time": monkey_target.strftime("%Y-%m-%d %H:%M")}
    assert am.accept_spontaneous(uid, payload) is None


# ═══════════════════════════════════════════════════════════════════
# scan_once：三闸门 + 推送三段
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_scan_sends_and_persists(env, monkeypatch, always_open_window):
    uid, cid = env
    calls = _make_push_ok(monkeypatch)
    now = datetime.now()
    with TestSyncSessionLocal() as db:
        msg = send_message_repo.create_pending(db, uid, "面试咋样了", now - timedelta(minutes=1))
        mid = msg.id

    n = await am.scan_once()
    assert n == 1
    assert len(calls) == 1 and calls[0]["user_id"] == uid
    payload = calls[0]["msg"]
    assert payload["type"] == "active" and payload["conversation_id"] == cid
    assert payload["msg"]["content"] == "面试咋样了"
    with TestSyncSessionLocal() as db:
        assert db.get(SendMessage, mid).status == "sent"
        # 落会话（hina 角色）+ 未读 +1 —— 对齐 dev/active 三段
        hinas = [m for m in db.query(Message).filter_by(conversation_id=cid, role="hina").all()]
        assert any(m.content == "面试咋样了" for m in hinas)
        assert db.get(Conversation, cid).unread_count == 1


@pytest.mark.asyncio
async def test_scan_grace_expires_old_msg(env, monkeypatch, always_open_window):
    """错过发送窗 2h：作废不补发——迟到的关心是骚扰"""
    uid, _ = env
    calls = _make_push_ok(monkeypatch)
    with TestSyncSessionLocal() as db:
        msg = send_message_repo.create_pending(db, uid, "凉了的关心", datetime.now() - timedelta(hours=3))
        mid = msg.id
    n = await am.scan_once()
    assert n == 0 and not calls
    with TestSyncSessionLocal() as db:
        assert db.get(SendMessage, mid).status == "expired"


@pytest.mark.asyncio
async def test_scan_quiet_hours_defers(env, monkeypatch):
    """静默时段：到点也不发，保持 pending 顺延"""
    uid, _ = env
    calls = _make_push_ok(monkeypatch)
    monkeypatch.setattr(am, "QUIET_START", 25)   # 人为制造"现在不在窗口"
    monkeypatch.setattr(am, "QUIET_END", 26)
    with TestSyncSessionLocal() as db:
        msg = send_message_repo.create_pending(db, uid, "夜里别发", datetime.now() - timedelta(minutes=1))
        mid = msg.id
    n = await am.scan_once()
    assert n == 0 and not calls
    with TestSyncSessionLocal() as db:
        assert db.get(SendMessage, mid).status == "pending"


@pytest.mark.asyncio
async def test_scan_crisis_do_not_disturb(env, monkeypatch, always_open_window):
    """危机勿扰：有未关闭事件的用户，AI 关心让位给人工"""
    uid, cid = env
    calls = _make_push_ok(monkeypatch)
    with TestSyncSessionLocal() as db:
        db.add(CrisisEvent(user_id=uid, conversation_id=cid, risk_level="中危",
                           trigger="test", signal="test", status="comforting"))
        db.commit()
        msg = send_message_repo.create_pending(db, uid, "这时候别插话", datetime.now() - timedelta(minutes=1))
        mid = msg.id
    n = await am.scan_once()
    assert n == 0 and not calls
    with TestSyncSessionLocal() as db:
        assert db.get(SendMessage, mid).status == "pending"


@pytest.mark.asyncio
async def test_scan_push_failure_bumps(env, monkeypatch, always_open_window):
    """推送失败：fail_count+1 保持 pending 下轮重试（3 次才烧成 cancelled，repo 层已测）"""
    uid, _ = env
    calls = _make_push_ok(monkeypatch, ok=False)
    with TestSyncSessionLocal() as db:
        msg = send_message_repo.create_pending(db, uid, "发不出去", datetime.now() - timedelta(minutes=1))
        mid = msg.id
    n = await am.scan_once()
    assert n == 0 and len(calls) == 1
    with TestSyncSessionLocal() as db:
        reloaded = db.get(SendMessage, mid)
        assert reloaded.status == "pending" and reloaded.fail_count == 1


# ═══════════════════════════════════════════════════════════════════
# agent 侧：spontaneous 节点（假模型，零网络）
# ═══════════════════════════════════════════════════════════════════

def _import_spontaneous():
    """借 agent_service 的 sys.path 挂载 import agent 层（backend 侧唯一正道）"""
    import app.ws.services.agent_service  # noqa: F401  (触发 sys.path 注入)
    import agent_hina.nodes.spontaneous as sp
    return sp


def _fake_model(content):
    class _M:
        def invoke(self, prompt):
            from types import SimpleNamespace
            return SimpleNamespace(content=content)
    return _M()


def test_spontaneous_node_parses_payload(monkeypatch):
    sp = _import_spontaneous()
    monkeypatch.setattr(sp, "spontaneous_model",
                        _fake_model('{"content": "考完了吧？咋样", "time": "2026-09-02 15:00"}'))
    out = sp.spontaneous_thought_node({  # type: ignore[arg-type]
        "short_session_memory": [{"role": "user", "content": "明天考试"}],
        "long_session_memory": [],
    })
    assert out == {"_spontaneous": {"content": "考完了吧？咋样", "time": "2026-09-02 15:00"}}


@pytest.mark.parametrize("raw", ["[]", "   ", "今天天气不错", '{"content": "缺时间"}'])
def test_spontaneous_node_no_care_or_garbage(monkeypatch, raw):
    sp = _import_spontaneous()
    monkeypatch.setattr(sp, "spontaneous_model", _fake_model(raw))
    assert sp.spontaneous_thought_node({  # type: ignore[arg-type]
        "short_session_memory": [{"role": "user", "content": "随便聊聊"}],
    }) == {}


def test_spontaneous_node_swallows_llm_error(monkeypatch):
    """铁律：思考炸了不能连累记忆压缩（节点在 save_memory 之前跑）"""
    sp = _import_spontaneous()

    class _Boom:
        def invoke(self, prompt):
            raise RuntimeError("API 炸了")
    monkeypatch.setattr(sp, "spontaneous_model", _Boom())
    assert sp.spontaneous_thought_node({  # type: ignore[arg-type]
        "short_session_memory": [{"role": "user", "content": "hello"}],
    }) == {}


def test_spontaneous_node_skips_empty_short(monkeypatch):
    """这轮没聊出东西（short 为空）→ 根本不调 LLM"""
    sp = _import_spontaneous()

    class _NoCall:
        def invoke(self, prompt):
            raise AssertionError("short 为空不该调 LLM")
    monkeypatch.setattr(sp, "spontaneous_model", _NoCall())
    assert sp.spontaneous_thought_node({"short_session_memory": []}) == {}  # type: ignore[dict-item]


# ═══════════════════════════════════════════════════════════════════
# backend 接线：_post_chat_flow 把 _spontaneous 转交落库
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_post_chat_flow_hands_spontaneous_to_service(monkeypatch):
    from app.ws.services import agent_service as svc

    seen: list[tuple[int, dict]] = []

    async def fake_compress(config, graph):
        return {"_spontaneous": {"content": "x", "time": "t"}}
    monkeypatch.setattr(svc, "run_memory_compression", fake_compress)
    import app.services.active_message as am_mod
    monkeypatch.setattr(am_mod, "accept_spontaneous",
                        lambda uid, payload: seen.append((uid, payload)) or 1)

    await svc._post_chat_flow({}, None, 42)
    assert seen == [(42, {"content": "x", "time": "t"})]


@pytest.mark.asyncio
async def test_post_chat_flow_silent_when_no_spontaneous(monkeypatch):
    from app.ws.services import agent_service as svc

    called: list = []

    async def fake_compress(config, graph):
        return {}
    monkeypatch.setattr(svc, "run_memory_compression", fake_compress)
    import app.services.active_message as am_mod
    monkeypatch.setattr(am_mod, "accept_spontaneous",
                        lambda uid, payload: called.append(1))

    await svc._post_chat_flow({}, None, 42)
    assert called == []
