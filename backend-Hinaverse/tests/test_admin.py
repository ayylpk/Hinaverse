"""
运营台统计接口测试（/api/admin，9/7 拍板第二批）。

数据隔离策略：统计是全局口径，同 session 里其他用例（如 test_messages 的 carol/dave）
会留行，所以指标卡/趋势/分布全部用「基线快照 → 播种 → 断言差值」；
用户表/详情/画像用 q= 精确搜索或直接按 id 断言，天然行级隔离。

依赖本机 MySQL 测试库 hinaverse_test（conftest 统一连）。
"""
import pytest
from sqlalchemy import delete, select

from app.models import Checkin, Conversation, CrisisEvent, Message, User
from app.repositories import conversation_repo, crisis_repo, message_repo, user_repo
from app.services import agent_memory
from tests.conftest import TestSyncSessionLocal

PWD = "pass1234"


@pytest.fixture
def sweep_adm():
    """本文件专用清理：造过危机事件的用户，conftest 的 clean_users 会被
    crisis_events→conversations 的 FK 卡死（历史遗留，它不知道 FK 链），
    所以按用户名前缀 adm 自己按 FK 安全顺序扫：消息→危机→打卡→会话→用户。
    （其余 adm_ 开头的名字只有 test_admin_init 用过，它会自清，互不误伤。）"""
    yield
    with TestSyncSessionLocal() as db:
        ids = list(db.execute(select(User.id).where(User.username.like("adm%"))).scalars())
        if not ids:
            return
        conv_ids = list(db.execute(select(Conversation.id).where(Conversation.user_id.in_(ids))).scalars())
        if conv_ids:
            db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
        db.execute(delete(CrisisEvent).where(CrisisEvent.user_id.in_(ids)))
        db.execute(delete(Checkin).where(Checkin.user_id.in_(ids)))
        db.execute(delete(Conversation).where(Conversation.user_id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(ids)))
        db.commit()


async def _register_token(client, name: str) -> tuple[int, dict]:
    """注册用户并返回 (user_id, auth headers)。JWT 的 role 是请求时现查库的，
    所以升 admin 只需事后改库，token 不用重签。清理统一走 sweep_adm 夹具。"""
    r = await client.post("/api/auth/register", json={"username": name, "password": PWD})
    assert r.status_code == 201, r.text
    user_id = r.json()["user"]["id"]
    return user_id, {"Authorization": f"Bearer {r.json()['token']}"}


def _promote_admin(username: str) -> None:
    with TestSyncSessionLocal() as db:
        u = user_repo.get_by_username(db, username)
        assert u is not None
        u.role = "admin"
        db.commit()


def _seed_user_activity(
    user_id: int, conv_prefix: str, user_msgs: int, crisis: tuple[str, str] | None
) -> int:
    """给一个用户造：会话（含开场白 hina 1 条）+ N 条 user 消息 + 可选危机。
    crisis=(risk_level, status)；返回实际落库消息数（供差值断言）。"""
    with TestSyncSessionLocal() as db:
        conv = conversation_repo.create_with_opening(db, user_id)
        for i in range(user_msgs):
            message_repo.insert_one(db, conv.id, "user", f"{conv_prefix}-msg-{i}")
        if crisis is not None:
            crisis_repo.create(
                db, user_id=user_id, conversation_id=conv.id,
                risk_level=crisis[0], trigger="t", signal="s", status=crisis[1],
            )
        return 1 + user_msgs  # 开场白 + 用户发言


@pytest.mark.asyncio
async def test_admin_stats_requires_admin(client, sweep_adm):
    """无 token → 401；普通用户 token → 403（require_admin 已上移 security.py，行为不变）"""
    resp = await client.get("/api/admin/stats")
    assert resp.status_code == 401
    _, headers = await _register_token(client, "admstat_plain")
    resp2 = await client.get("/api/admin/stats", headers=headers)
    assert resp2.status_code == 403
    # 其余三个接口同样被 require_admin 挡（挑 detail 与 portrait 各试一条）
    assert (await client.get("/api/admin/users/1/detail", headers=headers)).status_code == 403
    assert (await client.get("/api/admin/users/1/portrait", headers=headers)).status_code == 403


@pytest.mark.asyncio
async def test_stats_baseline_delta(client, sweep_adm):
    """播种 2 活跃用户（A：3消息+高危未关闭；B：1消息+中危已关闭），
    断言指标卡/今日趋势/危机分布差值全对上。"""
    _, headers = await _register_token(client, "admroot_x")
    _promote_admin("admroot_x")

    base = (await client.get("/api/admin/stats", headers=headers)).json()
    bc, bt = base["cards"], base["trend"][-1]  # trend 末位 = 今天

    ua_id, _ = await _register_token(client, "admstat_a")
    ub_id, _ = await _register_token(client, "admstat_b")
    msgs_a = _seed_user_activity(ua_id, "a", user_msgs=2, crisis=("高危", "pending_human"))
    msgs_b = _seed_user_activity(ub_id, "b", user_msgs=1, crisis=("中危", "resolved"))
    assert (msgs_a, msgs_b) == (3, 2)

    after = (await client.get("/api/admin/stats", headers=headers)).json()
    ac, at = after["cards"], after["trend"][-1]

    assert ac["total_users"] == bc["total_users"] + 2
    assert ac["new_users_today"] == bc["new_users_today"] + 2
    assert ac["active_users_7d"] == bc["active_users_7d"] + 2
    assert ac["messages_7d"] == bc["messages_7d"] + msgs_a + msgs_b
    assert ac["open_crises"] == bc["open_crises"] + 1  # 只有 A 未关闭
    assert ac["online_users"] == bc["online_users"] == 0  # 测试进程无 WS 连接

    # 7 日趋势：今天多 2 用户 / 5 消息 / 2 危机；长度恒 7、末位是今天
    assert len(after["trend"]) == 7
    assert at["date"] == bt["date"]  # 同一自然日内跑测试
    assert at["new_users"] == bt["new_users"] + 2
    assert at["messages"] == bt["messages"] + msgs_a + msgs_b
    assert at["crises"] == bt["crises"] + 2

    def _dist_cell(rows, risk, st):
        return next((r["count"] for r in rows if r["risk_level"] == risk and r["status"] == st), 0)

    assert _dist_cell(after["crisis_dist"], "高危", "pending_human") == _dist_cell(base["crisis_dist"], "高危", "pending_human") + 1
    assert _dist_cell(after["crisis_dist"], "中危", "resolved") == _dist_cell(base["crisis_dist"], "中危", "resolved") + 1


@pytest.mark.asyncio
async def test_users_search_and_activity_columns(client, sweep_adm):
    """用户表：q 搜索精确圈定 2 行；发言数只计 role=user、末次活跃非空、危机数对上；分页 total 稳定"""
    _, headers = await _register_token(client, "admroot_y")
    _promote_admin("admroot_y")
    ua_id, _ = await _register_token(client, "admser_a")
    ub_id, _ = await _register_token(client, "admser_b")
    _seed_user_activity(ua_id, "a", user_msgs=3, crisis=None)
    _seed_user_activity(ub_id, "b", user_msgs=1, crisis=("低危", "comforting"))

    data = (await client.get("/api/admin/users", params={"q": "admser"}, headers=headers)).json()
    assert data["total"] == 2
    by_id = {row["id"]: row for row in data["items"]}
    assert by_id[ua_id]["msg_count"] == 3
    assert by_id[ua_id]["last_active"] is not None
    assert by_id[ua_id]["crisis_count"] == 0
    assert by_id[ub_id]["msg_count"] == 1
    assert by_id[ub_id]["crisis_count"] == 1

    # 分页：size=1 时 total 不变、只回 1 行
    paged = (await client.get("/api/admin/users", params={"q": "admser", "size": 1}, headers=headers)).json()
    assert paged["total"] == 2 and len(paged["items"]) == 1


@pytest.mark.asyncio
async def test_user_detail_and_404(client, sweep_adm):
    """详情抽屉：跨会话最近 20 条正序 + 危机史带昵称；不存在的用户 404"""
    _, headers = await _register_token(client, "admroot_z")
    _promote_admin("admroot_z")
    ua_id, ua_headers = await _register_token(client, "admdet_a")
    _seed_user_activity(ua_id, "d", user_msgs=2, crisis=("高危", "handling"))

    # 通过接口再造一个会话和消息（验证跨会话聚合，不只造数据那一条会话）
    conv2 = (await client.post("/api/conversations", headers=ua_headers)).json()
    with TestSyncSessionLocal() as db:
        message_repo.insert_one(db, conv2["id"], "user", "admdet-cross-conv")

    detail = (await client.get(f"/api/admin/users/{ua_id}/detail", headers=headers)).json()
    assert detail["user"]["id"] == ua_id
    assert detail["user"]["msg_count"] == 3  # 只计 role=user：2 + 跨会话 1
    contents = [m["content"] for m in detail["messages"]]
    assert contents[-1] == "admdet-cross-conv"  # id 正序，最新在最后
    assert len(detail["messages"]) == 5  # 两条会话各 1 条 hina 开场白 + 3 条 user
    assert len(detail["crises"]) == 1
    assert detail["crises"][0]["status"] == "handling"

    assert (await client.get("/api/admin/users/999999/detail", headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_portrait_forwarding(client, sweep_adm, monkeypatch):
    """画像转发：命中回显全文；AgentMemory 不可达（fake 返回 None）走空态；不存在的用户 404"""
    _, headers = await _register_token(client, "admroot_p")
    _promote_admin("admroot_p")
    ua_id, _ = await _register_token(client, "admpor_a")
    ub_id, _ = await _register_token(client, "admpor_b")

    async def fake_cached(user_id: int):
        return "画像：性格底色偏内敛，近期考研压力大" if user_id == ua_id else None

    monkeypatch.setattr(agent_memory, "get_portrait_cached", fake_cached)

    r1 = await client.get(f"/api/admin/users/{ua_id}/portrait", headers=headers)
    assert r1.status_code == 200
    assert r1.json() == {"user_id": ua_id, "portrait": "画像：性格底色偏内敛，近期考研压力大"}

    # 没画像/服务挂了都返回 None，HTTP 层不报错（前端画空态）
    r2 = await client.get(f"/api/admin/users/{ub_id}/portrait", headers=headers)
    assert r2.status_code == 200 and r2.json()["portrait"] is None

    assert (await client.get("/api/admin/users/999999/portrait", headers=headers)).status_code == 404
