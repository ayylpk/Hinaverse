"""
通用工具函数。
"""
from datetime import datetime


def now_hm() -> str:
    """返回当前时间 HH:mm，前端消息 time 字段直接用"""
    return datetime.now().strftime("%H:%M")
