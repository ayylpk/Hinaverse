"""
运营台首管理员注册测试（部署码 + 通道关闭）。

覆盖 4 条：① 码对 + 无 admin → 创建成功且 role=admin，注册后 status 变 false
          ② 码错 → 400  ③ 已有 admin → 400  ④ 未配置码 + is_admin=true → 403
另：用户端不带 is_admin 的注册恒产普通 user（既有 test_register_and_login 覆盖，
    这里补一条显式断言）。
"""
import pytest

from app import config as app_config

ADMIN_CODE = "test-init-code-2026"


@pytest.fixture
def admin_code(monkeypatch):
    """部署码已配置（patch 模块属性：auth.py 通过 config.ADMIN_INIT_CODE 引用）"""
    monkeypatch.setattr(app_config, "ADMIN_INIT_CODE", ADMIN_CODE)
    return ADMIN_CODE


@pytest.mark.asyncio
async def test_admin_register_success(client, admin_code, clean_users):
    """① 码对 + 无 admin → 201 且 role=admin；注册后通道自动关闭"""
    clean_users("adm_ok")
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "adm_ok",
            "password": "pass1234",
            "is_admin": True,
            "init_code": ADMIN_CODE,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "admin"

    # 注册后重新拉状态：已有 admin → 通道关闭
    st = await client.get("/api/auth/admin-register-status")
    assert st.status_code == 200
    assert st.json() == {"open": False}


@pytest.mark.asyncio
async def test_admin_register_wrong_code(client, admin_code, clean_users):
    """② 码错 → 400「邀请码错误」"""
    clean_users("adm_wrong")
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "adm_wrong",
            "password": "pass1234",
            "is_admin": True,
            "init_code": "wrong-code",
        },
    )
    assert resp.status_code == 400
    assert "邀请码" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_admin_register_already_exists(client, admin_code, clean_users):
    """③ 已有 admin → 第二个注册被拒 400「已存在管理员」"""
    clean_users("adm_first")
    clean_users("adm_second")
    # 先成功注册首个管理员
    r1 = await client.post(
        "/api/auth/register",
        json={
            "username": "adm_first",
            "password": "pass1234",
            "is_admin": True,
            "init_code": ADMIN_CODE,
        },
    )
    assert r1.status_code == 201

    # 再来一个 → 拒绝
    r2 = await client.post(
        "/api/auth/register",
        json={
            "username": "adm_second",
            "password": "pass1234",
            "is_admin": True,
            "init_code": ADMIN_CODE,
        },
    )
    assert r2.status_code == 400
    assert "已存在管理员" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_admin_register_closed(client, monkeypatch, clean_users):
    """④ 未配置部署码 + is_admin=true → 403「管理员注册未开放」"""
    clean_users("adm_closed")
    monkeypatch.setattr(app_config, "ADMIN_INIT_CODE", "")
    resp = await client.post(
        "/api/auth/register",
        json={
            "username": "adm_closed",
            "password": "pass1234",
            "is_admin": True,
            "init_code": "whatever",
        },
    )
    assert resp.status_code == 403
    assert "未开放" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_plain_register_never_admin(client, clean_users):
    """用户端注册（不带 is_admin）恒产普通 user，且不受部署码影响"""
    clean_users("plain_user")
    resp = await client.post(
        "/api/auth/register",
        json={"username": "plain_user", "password": "pass1234"},
    )
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "user"
