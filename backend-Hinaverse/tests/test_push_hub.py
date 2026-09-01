"""
OutboundHub reg_id 注入回归测试（9/1 断链修复）。
纯内存单测：假 PushChannel 捕获 msg，不碰 DB / 不发网络。
"""
import asyncio

from app.ws.Hub import OutboundHub


class _FakePushChannel:
    """记录最后一次 push_offline 收到的 (user_id, msg)"""

    def __init__(self):
        self.calls: list[tuple[int, dict]] = []

    async def push_offline(self, user_id, msg):
        self.calls.append((user_id, msg))
        return True


class _FakeWS:
    def __init__(self, fail=False):
        self.sent = []
        self._fail = fail

    async def send_json(self, msg):
        if self._fail:
            raise RuntimeError("boom")
        self.sent.append(msg)


def test_offline_injects_reg_id():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)
    hub.register_reg_id_lookup(lambda uid: f"rid-{uid}")
    msg = {"type": "system", "content": "hi"}
    assert asyncio.run(hub.push(7, msg)) is True
    uid, sent = channel.calls[0]
    assert uid == 7 and sent["_reg_id"] == "rid-7"
    # 不污染调用方 dict
    assert "_reg_id" not in msg


def test_no_lookup_registered_passthrough():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)
    asyncio.run(hub.push(1, {"type": "system", "content": "x"}))
    assert "_reg_id" not in channel.calls[0][1]


def test_empty_reg_id_not_injected():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)
    hub.register_reg_id_lookup(lambda uid: "")
    asyncio.run(hub.push(1, {"type": "system", "content": "x"}))
    assert "_reg_id" not in channel.calls[0][1]


def test_lookup_exception_degrades():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)

    def _boom(uid):
        raise RuntimeError("db down")

    hub.register_reg_id_lookup(_boom)
    assert asyncio.run(hub.push(1, {"type": "system", "content": "x"})) is True
    assert "_reg_id" not in channel.calls[0][1]


def test_online_ws_success_skips_lookup():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)
    called = []
    hub.register_reg_id_lookup(lambda uid: called.append(uid) or "rid")
    ws = _FakeWS()
    hub.register_ws(3, ws)
    assert asyncio.run(hub.push(3, {"type": "typing"})) is True
    assert ws.sent and called == [] and channel.calls == []


def test_ws_fail_falls_back_with_reg_id():
    channel = _FakePushChannel()
    hub = OutboundHub(channel)
    hub.register_reg_id_lookup(lambda uid: "rid-fb")
    hub.register_ws(5, _FakeWS(fail=True))
    assert asyncio.run(hub.push(5, {"type": "system", "content": "y"})) is True
    assert channel.calls[0][1]["_reg_id"] == "rid-fb"
