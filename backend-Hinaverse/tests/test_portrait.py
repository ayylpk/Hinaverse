"""
画像回流测试：不依赖真实 LLM/网络/MySQL。
覆盖三层：
  1. get_portrait_cached —— TTL 缓存：命中不重拉、过期重拉、失败降级旧值/None
  2. generate_reply —— backend 注入：initial 带 portrait；user_id=None 不拉画像；
     回复来自图
  3. agent_think_node —— agent 消费：portrait 进入【你们的关系】；缺省走兜底
"""
import asyncio
import sys
from pathlib import Path

import pytest

# ── 让 backend venv 能 import agent_hina（与 agent_service.py 同一套 sys.path 注入） ──
_AGENT_DIR = Path(__file__).resolve().parents[2] / "agent-Hinaverse"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402


def _run(coro):
    """测试内跑协程（pytest-asyncio 只管 async def 用例，普通函数里的手动等不加 mark）"""
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════
# 1. get_portrait_cached —— TTL 缓存语义
# ═══════════════════════════════════════════════════════════════════

def test_cache_hits_after_first_fetch(monkeypatch):
    """首次拉取后 TTL 内不再发网络请求（调用计数验证）"""
    import app.services.agent_memory as am

    calls = {"n": 0}

    async def fake_get_portrait(user_id):
        calls["n"] += 1
        return "画像A"

    monkeypatch.setattr(am, "get_portrait", fake_get_portrait)      # 拦截网络层
    monkeypatch.setattr(am, "_PORTRAIT_CACHE", {})                  # 清缓存防跨测试污染

    r1 = _run(am.get_portrait_cached(1))
    r2 = _run(am.get_portrait_cached(1))
    assert r1 == "画像A" and r2 == "画像A"
    assert calls["n"] == 1, "TTL 内第二次调用不应重新拉取"


def test_cache_refetches_after_expiry(monkeypatch):
    """TTL 过期后重新拉取并更新缓存"""
    import app.services.agent_memory as am

    values = iter(["画像A", "画像B"])

    async def fake_get_portrait(user_id):
        return next(values)

    monkeypatch.setattr(am, "get_portrait", fake_get_portrait)
    monkeypatch.setattr(am, "_PORTRAIT_CACHE", {})
    monkeypatch.setattr(am, "_PORTRAIT_TTL", 0)  # 强制每次过期

    r1 = _run(am.get_portrait_cached(1))
    r2 = _run(am.get_portrait_cached(1))
    assert r1 == "画像A" and r2 == "画像B"


def test_cache_fallback_to_stale_on_failure(monkeypatch):
    """拉取失败：有旧值用旧值；无旧值返回 None（绝不抛出）"""
    import app.services.agent_memory as am

    async def fake_get_portrait(user_id):
        return None  # 模拟 AgentMemory 拉取失败

    monkeypatch.setattr(am, "get_portrait", fake_get_portrait)
    monkeypatch.setattr(am, "_PORTRAIT_CACHE", {})
    monkeypatch.setattr(am, "_PORTRAIT_TTL", 0)

    # 情况 1：无旧值 → None
    assert _run(am.get_portrait_cached(1)) is None

    # 情况 2：有旧值（fetched_at=0 → 必然过期）+ 拉取失败 → 返回旧值
    am._PORTRAIT_CACHE[2] = ("旧画像", 0.0)
    assert _run(am.get_portrait_cached(2)) == "旧画像"


# ═══════════════════════════════════════════════════════════════════
# 2. generate_reply —— backend 注入画像到图状态
# ═══════════════════════════════════════════════════════════════════

class _Awaited:
    """把任意对象伪装成 awaitable（模拟 async _get_graph 的返回值）"""
    def __init__(self, obj):
        self._obj = obj

    def __await__(self):
        async def _wrap():
            return self._obj
        return _wrap().__await__()


class _FakeGraph:
    """假图：记录收到的 initial 状态，返回固定 AI 回复"""
    def __init__(self):
        self.received: dict | None = None

    async def ainvoke(self, initial: dict, config: dict) -> dict:
        self.received = initial
        return {"messages": [AIMessage(content="假图回复")]}


async def _noop_compression(*a, **k) -> None:
    """假 run_memory_compression：必须是 async 函数（被 create_task 调用，要返回真协程）"""
    return None


@pytest.mark.asyncio
async def test_generate_reply_injects_portrait(monkeypatch):
    """user_id 存在 → 拉画像并注入 initial['portrait']；回复来自图"""
    from app.ws.services import agent_service as svc

    drawn = {"n": 0}

    async def fake_portrait(user_id):
        drawn["n"] += 1
        return "这位用户喜欢深夜聊天，最近在准备考研"

    fake_graph = _FakeGraph()
    monkeypatch.setattr(svc, "_get_graph", lambda: _Awaited(fake_graph))
    monkeypatch.setattr(svc, "get_portrait_cached", fake_portrait)
    monkeypatch.setattr(svc, "run_memory_compression", _noop_compression)

    reply = await svc.generate_reply("你好", {}, user_id=42)
    assert reply == "假图回复"
    assert fake_graph.received["portrait"] == "这位用户喜欢深夜聊天，最近在准备考研"
    assert drawn["n"] == 1


@pytest.mark.asyncio
async def test_generate_reply_skips_portrait_without_user_id(monkeypatch):
    """user_id=None（dev 调试场景）→ 不拉画像、不注入 portrait"""
    from app.ws.services import agent_service as svc

    drawn = {"n": 0}

    async def fake_portrait(user_id):
        drawn["n"] += 1
        return "不应被调用"

    fake_graph = _FakeGraph()
    monkeypatch.setattr(svc, "_get_graph", lambda: _Awaited(fake_graph))
    monkeypatch.setattr(svc, "get_portrait_cached", fake_portrait)
    monkeypatch.setattr(svc, "run_memory_compression", _noop_compression)

    reply = await svc.generate_reply("你好", {}, user_id=None)
    assert reply == "假图回复"
    assert "portrait" not in fake_graph.received
    assert drawn["n"] == 0


# ═══════════════════════════════════════════════════════════════════
# 3. agent_think_node —— agent 侧消费画像
# ═══════════════════════════════════════════════════════════════════

class _FakeModel:
    """假 LLM：记录收到的提示词，返回固定回复（替掉 pydantic 绑定的真实模型）"""
    def __init__(self):
        self.seen_system = ""

    def invoke(self, messages):
        self.seen_system = messages[0].content
        return AIMessage(content="日奈的回复", tool_calls=[])


def _run_think(monkeypatch, state) -> str:
    """跑 agent_think_node，捕获发给 LLM 的 system prompt 文本"""
    from agent_hina.nodes import think

    fake_model = _FakeModel()
    monkeypatch.setattr(think, "model_with_tools", fake_model)  # 整个替换，绕开 pydantic setattr 限制
    think.agent_think_node(state)
    return fake_model.seen_system


def test_think_injects_portrait_into_relationship(monkeypatch):
    """画像存在 → 注入系统提示词的【你们的关系】段"""
    system_text = _run_think(monkeypatch, {
        "messages": [HumanMessage(content="今天好累")],
        "portrait": "用户是考研党，睡眠不好",
    })
    assert "用户是考研党，睡眠不好" in system_text


def test_think_uses_fallback_without_portrait(monkeypatch):
    """画像缺失 → 「暂无用户档案」兜底"""
    system_text = _run_think(monkeypatch, {
        "messages": [HumanMessage(content="今天好累")],
    })
    assert "暂无用户档案" in system_text