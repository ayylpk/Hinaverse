from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

load_dotenv()


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
#加载记忆
load_memory_model = create_model(0.2)
#执行工具
tool_model = create_model(0.1)
#寻求帮助
ask_human_model = create_model(0.5)
#选择
route_model = create_model(0.0)
#压缩记忆（内容大，给更长超时）
reduce_model = create_model(0.0, timeout=300)
#定时发消息/任务
schedule_model = create_model(0.9)
#判断是否应该产生想法
judge_model = create_model(0.0)
#写日记（内容大，给更长超时）
write_model = create_model(0.9, timeout=300)
