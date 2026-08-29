"""
models.py —— agent 层 LLM 模型统一封装（唯一入口）

所有需要调 LLM 的地方（聊天 / 记忆压缩 / 安全检测 / 澄清 / 主动消息）
都用这里的模型实例，不自行发 HTTP 请求。backend 通过 import agent_hina.* 复用本封装。

注意：显式加载 agent-Hinaverse/.env（与 graph.py 一致），
保证被 backend import 时（cwd 在 backend 目录）也能读到 DEEPSEEK_API_KEY 等配置。
"""
from pathlib import Path
from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# 显式加载本项目的 .env，不依赖调用方的工作目录
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_FILE)


def create_model(temperature: float = 0.7, timeout: int = 120):
    return ChatDeepSeek(
        model="deepseek-v4-flash",
        temperature=temperature,
        timeout=timeout,  # API 超时（秒），防止无限等待
        extra_body={"thinking": {"type": "disabled"}},
    )

#聊天
chat_model = create_model(0.8)
#存储记忆
save_memory_model = create_model(0.2)
#寻求帮助
ask_human_model = create_model(0.5)
#压缩记忆（内容大，给更长超时）
reduce_model = create_model(0.0, timeout=300)
#写日记/日终总结（内容大，给更长超时）
write_model = create_model(0.9, timeout=300)
