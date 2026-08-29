"""
安全检测服务 —— 转发薄壳（不再包含任何 AI 逻辑）

所有 AI 能力已收口到 agent 层：
    agent-Hinaverse/agent_hina/safety.py
      ├─ check_message()            三阶段漏斗安全检测
      ├─ generate_high_risk_summary() 高危快速摘要（最近对话浓缩）
      └─ SafetyResult              检测结果模型

本文件只做 import 转发，保持 ws.py 的引用不变：
    from app.services.safety_service import check_message, ...

AI 相关的模型、提示词、LLM 调用全部在 agent 层（models.py / prompts.py / safety.py），
backend 只做编排（收消息、落库、路由、推送）。
"""
import sys
from pathlib import Path

# 复用 agent-Hinaverse 的 AI 资产（safety.py 仅依赖 prompts/datetime/models，可安全导入）
# 本文件位于 backend-Hinaverse/app/ws/services/ 下：parents[0]=services, [1]=ws, [2]=app, [3]=backend, [4]=项目根
_AGENT_DIR = Path(__file__).resolve().parents[4] / "agent-Hinaverse"
if str(_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(_AGENT_DIR))

from agent_hina.safety import (  # noqa: E402
    SafetyResult,
    check_message,
    generate_high_risk_summary,
)

__all__ = [
    "SafetyResult",
    "check_message",
    "generate_high_risk_summary",
]
