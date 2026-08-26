"""
日奈 AI 服务入口
用法: python run.py
也可: uvicorn server.app:app --host 0.0.0.0 --port 8000
"""
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server.app:app", host="0.0.0.0", port=8000, reload=True)
