"""
repositories —— 数据访问层（DAO）。

规则：
    1. 所有业务查询必须走这里，禁止在路由/WS 里裸写 select / db.add。
    2. 函数一律同步，接收 Session 参数（由调用方从 SessionLocal / get_db 获取）。
    3. 每个函数内部自行 commit（事务粒度 = 单次调用）。
"""
from app.repositories.user_repo import *
from app.repositories.conversation_repo import *
from app.repositories.message_repo import *
from app.repositories.crisis_repo import *
from app.repositories.daily_repo import *
from app.repositories.send_message_repo import *
from app.repositories.diary_repo import *
from app.repositories.high_risk_repo import *
