"""
会话相关测试：新建会话 + 列表。
"""
import pytest


@pytest.mark.asyncio
async def test_create_and_list_conversations(client):
    # 先注册登录
    await client.post(
        "/api/auth/register",
        json={"username": "bob", "password": "pass1234"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "bob", "password": "pass1234"},
    )
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 新建会话
    resp = await client.post("/api/conversations", headers=headers)
    assert resp.status_code == 201
    conv = resp.json()
    assert conv["id"]
    assert conv["unread_count"] == 0
    # 开场白非空
    assert conv["last_message"]

    # 列表
    resp2 = await client.get("/api/conversations", headers=headers)
    assert resp2.status_code == 200
    convs = resp2.json()
    assert len(convs) >= 1
    assert convs[0]["last_message"]

    # 未鉴权访问应 401
    resp3 = await client.get("/api/conversations")
    assert resp3.status_code == 401
