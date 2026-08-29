"""
high_risk_repo —— 高危摘要表（high_risk_summaries）数据访问。

高危确认后，快速生成的对话浓缩摘要落库到这里（id / user_id / content 三列）。
独立成文件，与其它业务 DAO 隔离。
"""
from sqlalchemy.orm import Session

from app.models import HighRiskSummary


def create_summary(db: Session, user_id: int, content: str) -> HighRiskSummary:
    """插入一条高危摘要并提交，返回带 id 的记录"""
    row = HighRiskSummary(user_id=user_id, content=content)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
