"""
spontaneous 节点 —— 对话收尾「自主关心」（先于记忆压缩执行，见 graph.run_memory_compression）

语义（阶段 4：存数据库 + 统一扫描触发）：
    用户每聊完一轮，日奈顺手想一条"等ta安静下来之后该关心什么"——
    产出成品正文 + 送达时间，交给 backend 落 send_messages（pending）。
    用户若再说话，backend 会先撤销这条（人都来了，不用发消息关心）；
    直到用户不再来，这条才由扫描循环到点发出。每用户任意时刻至多一条。

设计约束：
    - 本节点不碰数据库（agent 层规矩：产出 state 字段，backend 取走落库，
      同 daily_compress 的 _daily_summary_text 模式）
    - 绝不允许炸：思考失败 = 没有主动消息而已，绝不能连累后面的记忆压缩
    - 时间窗口/静默时段/长度这些"发送政策"校验在 backend active_message 服务做，
      节点只做 JSON 形状解析（生成与执法分离）
"""
import json
import re
from datetime import datetime

from agent_hina.state import AgentState
from agent_hina.models import spontaneous_model
from agent_hina.prompts import build_spontaneous_prompt


def spontaneous_thought_node(state: AgentState) -> dict:
    """
    返回 {"_spontaneous": {"content": 成品正文, "time": "YYYY-MM-DD HH:MM"}} 或 {}。
    _spontaneous 是一次性产物：只随 run_memory_compression 的返回值交还 backend，
    ⚠️ 不写回 checkpoint（不是记忆，写回去会污染下一轮 state）。
    """
    short_mem = state.get("short_session_memory", [])
    if not isinstance(short_mem, list) or not short_mem:
        # 这轮没聊出东西（short 为空），没得可惦记
        return {}

    # short 记忆 → 可读对话文本（格式与 save_memory 保持一致）
    conversation_text = "\n".join(
        [f"{m.get('role', '?')}: {m.get('content', '')}" for m in short_mem]
    )
    # 长记忆 / 画像：提供"刚才没提但一直挂着"的背景（如昨天说的今天开考）
    long_mem = state.get("long_session_memory", [])
    if isinstance(long_mem, list) and long_mem:
        long_text = "\n".join(
            [f"- {m.get('content', '')}" for m in long_mem if m.get("content")]
        )
    else:
        long_text = str(long_mem) if isinstance(long_mem, str) else ""

    now = datetime.now()
    prompt = build_spontaneous_prompt(
        current_time=now.strftime("%Y-%m-%d %H:%M"),
        conversation_text=conversation_text,
        long_memory_text=long_text,
        relationship_context=state.get("portrait", ""),
    )

    try:
        response = spontaneous_model.invoke(prompt)
        raw = (response.content or "").strip()  # type: ignore
        result = _parse_result(raw)
        if result is None:
            print("  [spontaneous] 没啥可关心的（或输出无法解析），本轮不发主动消息")
            return {}
        content, time_str = result
        print(f"  [spontaneous] 想好了：{time_str} 发「{content[:30]}…」")
        return {"_spontaneous": {"content": content, "time": time_str}}
    except Exception as e:
        # 铁律：思考失败不能连累记忆压缩（本函数在 save_memory 之前跑）
        print(f"  [spontaneous] LLM 调用失败: {e}（跳过，不影响压缩）")
        return {}


def _parse_result(raw: str) -> tuple[str, str] | None:
    """
    容错解析 LLM 输出 → (content, time)，不值得关心/解析失败返回 None。
    接受形态：{"content":...,"time":...} / [] / [{...}]（多取第一条）。
    """
    if not raw:
        return None

    parsed = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # 从裹了废话的输出里抠出第一个 JSON 对象或数组
        m = re.search(r"\{[\s\S]*?\}", raw) or re.search(r"\[[\s\S]*?\]", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    if parsed is None:
        return None

    # 空数组 = LLM 明确判断"没啥好关心的"
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else None
    if not isinstance(parsed, dict):
        return None

    content = str(parsed.get("content", "")).strip()
    time_str = str(parsed.get("time", "")).strip()
    if not content or not time_str:
        return None
    # 只要时间格式合法即可（窗口/静默政策校验在 backend 做）
    try:
        datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return content, time_str
