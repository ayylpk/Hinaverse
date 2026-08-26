"""
全局配置：从环境变量读取，开发期允许缺省。
"""
import os
from pathlib import Path

# 项目根目录（backend-Hinaverse/）
BASE_DIR = Path(__file__).resolve().parent.parent

# ── 安全 ──
# 生产环境必须通过环境变量注入，开发期用固定值兜底（需 ≥32 字节，避免 PyJWT 警告）
SECRET_KEY = os.getenv("HINA_SECRET_KEY", "hinaverse-dev-secret-please-change-me-now-2026")
JWT_ALGORITHM = "HS256"
# token 有效期：7 天
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7

# ── 数据库 ──
# SQLite 异步驱动；文件放在项目根目录，重启不丢数据
DB_URL = os.getenv("HINA_DB_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'hina.db'}")

# ── 极光推送（可选，缺失时静默降级）──
JPUSH_APP_KEY = os.getenv("JPUSH_APP_KEY", "")
JPUSH_MASTER_SECRET = os.getenv("JPUSH_MASTER_SECRET", "")
JPUSH_URL = "https://api.jpush.cn/v3/push"

# ── CORS ──
# 前端开发端口，生产按需调整
CORS_ORIGINS = os.getenv("HINA_CORS_ORIGINS", "*").split(",")
