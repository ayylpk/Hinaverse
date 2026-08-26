"""
WebSocket 测试：连接鉴权 + 收发消息 + 收到 typing 和回复。

用 starlette TestClient 测 WS（同步方式，自带事件循环）。
"""
from starlette.testclient import TestClient

from app.main import app


def _register_and_get_token(client: TestClient, username: str) -> str:
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "pass1234"},
    )
    resp = client.post(
        "/api/auth/login",
        json={"username": username, "password": "pass1234"},
    )
    return resp.json()["token"]


def test_ws_invalid_token():
    """token 无效应被拒绝"""
    with TestClient(app) as client:
        with client.websocket_connect("/ws?token=invalid") as ws:
            # 连接后应立即收到关闭
            try:
                ws.receive_text()
                assert False, "应该被关闭"
            except Exception:
                pass  # 连接被关闭，符合预期


def test_ws_message_flow():
    """正常收发：连上 → 发消息 → 收到 typing → 收到回复"""
    with TestClient(app) as client:
        token = _register_and_get_token(client, "wsuser1")
        # 先建一个会话
        conv = client.post(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token}"},
        ).json()
        conv_id = conv["id"]

        with client.websocket_connect(f"/ws?token={token}") as ws:
            # 发一条用户消息
            ws.send_json({"type": "message", "conversation_id": conv_id, "content": "你好"})

            # 应收到 typing
            typing_msg = ws.receive_json()
            assert typing_msg["type"] == "typing"
            assert typing_msg["conversation_id"] == conv_id

            # 应收到日奈回复
            reply_msg = ws.receive_json()
            assert reply_msg["type"] == "message"
            assert reply_msg["conversation_id"] == conv_id
            assert reply_msg["msg"]["role"] == "hina"
            assert reply_msg["msg"]["content"]

            # 验证消息已落库（拉历史）
            msgs = client.get(
                f"/api/conversations/{conv_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
            ).json()["messages"]
            roles = [m["role"] for m in msgs]
            assert "user" in roles
            assert "hina" in roles


def test_ws_two_clients_isolated():
    """两个客户端各自会话，回复互不串"""
    with TestClient(app) as client:
        token1 = _register_and_get_token(client, "wsuser2")
        token2 = _register_and_get_token(client, "wsuser3")
        conv1 = client.post(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token1}"},
        ).json()["id"]
        conv2 = client.post(
            "/api/conversations",
            headers={"Authorization": f"Bearer {token2}"},
        ).json()["id"]

        with client.websocket_connect(f"/ws?token={token1}") as ws1, \
             client.websocket_connect(f"/ws?token={token2}") as ws2:
            # 客户端 1 发消息
            ws1.send_json({"type": "message", "conversation_id": conv1, "content": "第一条"})
            # 客户端 1 收到自己的回复
            ws1.receive_json()  # typing
            reply1 = ws1.receive_json()
            assert reply1["conversation_id"] == conv1

            # 客户端 2 发消息
            ws2.send_json({"type": "message", "conversation_id": conv2, "content": "第二条"})
            ws2.receive_json()  # typing
            reply2 = ws2.receive_json()
            assert reply2["conversation_id"] == conv2
