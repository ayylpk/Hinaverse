"""
消息游标分页测试。
"""
import pytest


@pytest.mark.asyncio
async def test_message_cursor_pagination(client):
    # 注册登录
    await client.post(
        "/api/auth/register",
        json={"username": "carol", "password": "pass1234"},
    )
    login = await client.post(
        "/api/auth/login",
        json={"username": "carol", "password": "pass1234"},
    )
    token = login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 新建会话（含 1 条开场白）
    conv = (await client.post("/api/conversations", headers=headers)).json()
    conv_id = conv["id"]

    # 默认拉取：应有 1 条开场白
    resp = await client.get(f"/api/conversations/{conv_id}/messages", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["messages"]) == 1
    assert data["messages"][0]["role"] == "hina"
    assert data["has_more"] is False

    # 已读清零
    resp_read = await client.post(f"/api/conversations/{conv_id}/read", headers=headers)
    assert resp_read.status_code == 200

    # 越权访问别人的会话应 404（用另一个用户）
    await client.post(
        "/api/auth/register",
        json={"username": "dave", "password": "pass1234"},
    )
    login2 = await client.post(
        "/api/auth/login",
        json={"username": "dave", "password": "pass1234"},
    )
    token2 = login2.json()["token"]
    headers2 = {"Authorization": f"Bearer {token2}"}
    resp_other = await client.get(
        f"/api/conversations/{conv_id}/messages", headers=headers2
    )
    assert resp_other.status_code == 404
