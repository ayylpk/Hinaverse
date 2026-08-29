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

# ── DeepSeek LLM（安全检测用）──
# 优先读环境变量；缺失时回退读取 agent-Hinaverse/.env（开发期复用同一 key）
_AGENT_ENV = BASE_DIR.parent / "agent-Hinaverse" / ".env"
if not os.getenv("DEEPSEEK_API_KEY") and _AGENT_ENV.exists():
    for _line in _AGENT_ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# ── AgentMemory 记忆服务（外部，X-Project 租户隔离）──
# 两个业务接口：
#   POST /api/echo      推消息进记忆管线（L0→L1→L3 异步消化）
#   GET  /api/portrait?userId=  查用户画像
# 请求头：X-Project（表前缀隔离）+ X-Api-Key（项目专属密钥）。
# Key 属于服务端配置，绝不下发到浏览器（前端只跟本后端说话）。
# 开发期指向本机 AgentMemory（bun run index.ts 默认端口 3001）；生产改为服务器地址
AGENT_MEMORY_BASE_URL = os.getenv("AGENT_MEMORY_BASE_URL", "http://localhost:3001")
AGENT_MEMORY_PROJECT = os.getenv("AGENT_MEMORY_PROJECT", "Hinaverse")
AGENT_MEMORY_API_KEY = os.getenv(
    "AGENT_MEMORY_API_KEY", "5223f238de4486503cee8b95a8e2e37318af28d17f33cc859139ceb7eef3fd0e"
)
