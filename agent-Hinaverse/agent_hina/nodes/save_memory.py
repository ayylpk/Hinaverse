"""
save_memory 节点 —— 提取对话记忆摘要，存入 Chroma，并生成上次对话收尾写入关系档案
"""
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from agent_hina.models import save_memory_model, chat_model
from agent_hina.state import AgentState
from agent_hina.memory_store import get_collection
from agent_hina.prompts import build_memory_save_prompt

load_dotenv()


def save_memory_node(state: AgentState) -> dict:
    """
    记忆存储节点：提取对话内容，生成日奈视角的记忆摘要，并附带结构化 Metadata 存入 Chroma。
    """

    raw_memory = state.get("short_session_memory", [])
    if isinstance(raw_memory, list) and raw_memory:
        # 转成可读文本，每条 "role: content"
        memory_content = "\n".join(
            [f"{m.get('role', '?')}: {m.get('content', '')}" for m in raw_memory]
        )
    elif isinstance(raw_memory, str):
        memory_content = raw_memory
    else:
        memory_content = ""

    if not memory_content:
        print("  [save_memory] 记忆内容为空，跳过存储。")
        # 即使没有新记忆，也要保留已压缩的 long_session_memory
        # 否则后台闹钟每次压缩完就丢掉，下次又触发压缩（死循环）
        return {"need_to_save_memory": False}

    # 2. 构建系统提示词 (Prompt)
    now = datetime.now()
    formatted = now.strftime("%Y年%m月%d日%H时")

    system_prompt = build_memory_save_prompt(formatted, memory_content)

    # 3. 调用大模型并解析 JSON
    try:
        response = save_memory_model.invoke(system_prompt)
        raw_output = response.content.strip()  # type: ignore

        if raw_output.startswith("```"):
            raw_output = raw_output.split("\n", 1)[-1].rsplit("```", 1)[0]

        memory_data = json.loads(raw_output)
    except Exception as e:
        print(f"  [save_memory] JSON解析失败,降级为普通文本存储: {e}")
        memory_data = {
            "summary": raw_output if 'raw_output' in locals() else memory_content,  # type: ignore
            "keywords": [],
            "memory_type": "episodic",
            "importance_score": 0.5
        }

    # 4. 准备 Chroma 写入数据
    doc_id = str(uuid.uuid4())[:12]
    summary = memory_data.get("summary", "")

    metadata = {
        "timestamp": datetime.now().isoformat(),
        "keywords": ",".join(memory_data.get("keywords", [])),
        "memory_type": memory_data.get("memory_type", "episodic"),
        "importance_score": float(memory_data.get("importance_score", 0.5))
    }

    # 5. 写入 Chroma 数据库
    collection = get_collection()
    try:
        collection.add(
            ids=[doc_id],
            documents=[summary],  # 存入日奈视角的摘要
            metadatas=[metadata],
        )
        print(f"  [save_memory] 成功存入 (id={doc_id}, type={metadata['memory_type']}): {summary[:50]}...")
    except Exception as e:
        print(f"  [save_memory] 存入 Chroma 失败: {e}")

    # 6. 追加到 long_session_memory（供 reduce 中度压缩 / 跨天接续）
    long_mem = list(state.get("long_session_memory", []))
    long_mem.append({"role": "system", "content": summary})

    return {
        "need_to_save_memory": False,
        "long_session_memory": long_mem,
        "short_session_memory":[{"role": "system", "content": summary}]   # 阶段性结束，清空本轮对话
    }
