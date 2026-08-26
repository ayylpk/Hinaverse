"""
认证相关测试：注册 / 登录 / me。
"""
import pytest


@pytest.mark.asyncio
async def test_register_and_login(client):
    # 注册
    resp = await client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "pass1234"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "token" in data
    assert data["user"]["username"] == "alice"
    # 昵称非空（随机生成）
    assert data["user"]["nickname"]
    # 头像空串
    assert data["user"]["avatar"] == ""

    # 重复注册应失败
    resp2 = await client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "pass1234"},
    )
    assert resp2.status_code == 400

    # 登录
    resp3 = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "pass1234"},
    )
    assert resp3.status_code == 200
    token = resp3.json()["token"]

    # 用 token 访问 /me
    resp4 = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp4.status_code == 200
    assert resp4.json()["username"] == "alice"

    # 错误密码
    resp5 = await client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrong"},
    )
    assert resp5.status_code == 401
