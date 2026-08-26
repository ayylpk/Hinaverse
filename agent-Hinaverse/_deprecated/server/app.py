import asyncio
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

_sqlite_dir = Path(__file__).parent
if str(_sqlite_dir) not in sys.path:
    sys.path.insert(0, str(_sqlite_dir))

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ⚠️ 必须在任何 os.getenv 之前加载 .env（否则 HINA_API_KEY 等读不到）
from dotenv import load_dotenv
load_dotenv(_project_root / ".env")

from agent_hina import prompts

CHATTING_CODE = 3
CHATTING_MODE_STR = str(CHATTING_CODE)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# ── 导入所有 REST 路由 ──
from server.routers.ChattingRecordsRouter import router as chat_router
from server.routers.ImRecordsRouter import router as im_router
from server.routers.DiaryOfHinaRouter import router as hina_diary_router
from server.routers.DiaryOfMeRouter import router as me_diary_router
from server.routers.KaomojiRouter import router as kaomoji_router
from server.routers.PhotoRouter import router as photo_router
from server.routers.ContextRouter import router as context_router

# ── LangGraph agent（延迟初始化） ──
_GRAPH = None
_AGENT_AVAILABLE = False
build_hina_graph = None  # type: ignore
analysis = None  # type: ignore
TIMELINE_FILE = Path(__file__).resolve().parent.parent / "data" / "time-line.md"

app = FastAPI()


@app.on_event("startup")
async def _init_agent():
    global _GRAPH, _AGENT_AVAILABLE, build_hina_graph, analysis
    try:
        from agent_hina.graph import build_hina_graph as _build_graph
        from agent_hina.nodes.schedule import analysis as _analysis, TIMELINE_FILE as _timeline
        build_hina_graph = _build_graph
        analysis = _analysis
        TIMELINE_FILE = _timeline
        _GRAPH = await build_hina_graph()
        _AGENT_AVAILABLE = True
        app.state.hina_graph = _GRAPH
        print("[startup] LangGraph agent 已加载")
        # 启动全局闹钟扫描（不依赖 WebSocket 连接）
        asyncio.create_task(_global_alarm_loop())
    except Exception as e:
        _AGENT_AVAILABLE = False
        print(f"[startup] LangGraph agent 加载失败，使用 echo 模式: {e}")


async def _global_alarm_loop():
    """全局闹钟扫描——不依赖 WebSocket，随服务启动一直跑。
    闹钟到期时自己跑 agent，结果通过极光推送发出。"""
    print("  [global-alarm] 全局闹钟扫描已启动")
    await asyncio.sleep(3)  # 等服务完全就绪
    while True:
        try:
            if not _AGENT_AVAILABLE or _GRAPH is None:
                await asyncio.sleep(5)
                continue

            now = datetime.now()
            if not TIMELINE_FILE.exists():
                await asyncio.sleep(1)
                continue

            content = TIMELINE_FILE.read_text(encoding="utf-8")
            state_alarms = read_alarms_by_type(content, "状态")
            active_alarms = read_alarms_by_type(content, "主动")
            fired = False

            for t, reason in state_alarms:
                if t <= now:
                    remove_alarm(t)
                    print(f"  [global-alarm] 状态闹钟触发: {reason}")
                    await _run_agent_with_timeout("state", reason)
                    fired = True
                    break

            if not fired:
                for t, reason in active_alarms:
                    if t <= now:
                        remove_alarm(t)
                        print(f"  [global-alarm] 主动闹钟触发: {reason}")
                        await _run_agent_with_timeout("active", reason)
                        break
        except Exception as e:
            print(f"  [global-alarm] 异常: {e}")
            traceback.print_exc()
        await asyncio.sleep(1)


ALARM_TIMEOUT = 600  # agent 单次运行超时（秒），防止 API 卡死阻塞整个闹钟循环
_BG_LONG_FILE = Path(__file__).resolve().parent.parent / "data" / "background_long.json"


def _load_background_long() -> list:
    """从文件加载上次后台运行压缩后的 long_session_memory"""
    try:
        if _BG_LONG_FILE.exists():
            import json
            data = json.loads(_BG_LONG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list) and data:
                return data
    except Exception:
        pass
    return []


def _save_background_long(long_mem: list):
    """保存压缩后的 long_session_memory 到文件，供下次后台运行加载"""
    try:
        import json
        _BG_LONG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _BG_LONG_FILE.write_text(json.dumps(long_mem, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"  [global-alarm] 保存 long 文件失败: {e}")


async def _run_agent_with_timeout(msg_type: str, reason: str):
    """带超时的 agent 运行，防止 API 卡死阻塞闹钟循环"""
    try:
        await asyncio.wait_for(
            _run_agent_and_push(msg_type, reason),
            timeout=ALARM_TIMEOUT,
        )
    except asyncio.TimeoutError:
        print(f"  [global-alarm] ⏰ agent 运行超时 ({ALARM_TIMEOUT}s)，已取消")


async def _run_agent_and_push(msg_type: str, reason: str):
    """独立运行 agent → 存 DB → 极光推送"""
    from server.ws_handler import build_state_input, extract_agent_reply
    from agent_hina import prompts
    try:
        # ── 解析 0/1 模式前缀，决定 IM（0）还是现实（1）模式 ──
        chatting_mode = 1  # 默认现实模式
        clean_reason = reason
        if reason and reason[0] in "01":
            chatting_mode = int(reason[0])
            clean_reason = reason[1:]
        # 设置对应的 system prompt
        if chatting_mode == 0:
            prompts.SYSTEM_PROMPT = prompts.HINA_IM_PROMPT
        else:
            prompts.SYSTEM_PROMPT = prompts.HINA_SYSTEM_PROMPT

        state_input = build_state_input(msg_type, clean_reason)

        # ── 补充长期记忆上下文（#4 修复：后台 agent 不能失忆）──
        # 优先从文件加载压缩后的 long（上次运行 reduce 的结果），没有再从 Chroma 取
        long_mem = _load_background_long()
        if long_mem:
            state_input["long_session_memory"] = long_mem
            print(f"  [global-alarm] 从文件加载了压缩后的记忆 ({len(long_mem)} 条)")
        else:
            try:
                from agent_hina.memory_store import get_collection
                coll = get_collection()
                all_data = coll.get(limit=10, include=["documents", "metadatas"])
                if all_data and all_data.get("documents"):
                    memories = []
                    for i, doc in enumerate(all_data["documents"]):
                        meta = all_data["metadatas"][i] if all_data.get("metadatas") else {}
                        memories.append({"content": doc, "type": meta.get("memory_type", "")})
                    state_input["long_session_memory"] = memories
                    print(f"  [global-alarm] 从 Chroma 加载了 {len(memories)} 条记忆作为上下文")
            except Exception as _mem_e:
                print(f"  [global-alarm] 记忆加载失败: {_mem_e}")

        config = {"configurable": {"thread_id": "background"}}
        result = await _GRAPH.ainvoke(state_input, config) # type: ignore
        reply = extract_agent_reply(result)
        reply_text = reply.get("reply_text", "")

        # ── 0/1 模式前缀只加在推送给 Android 的文本上，DB 存无前缀原文（与 WS 路径一致）──
        push_text = str(chatting_mode) + reply_text if reply_text else ""

        # ── 持久化压缩后的 long_session_memory（文件），下次后台运行直接加载 ──
        long_after = result.get("long_session_memory", [])
        if long_after:
            _save_background_long(long_after)

        # ── graph 跑完后清理旧 checkpoint（#1 修复：只清 background 线程）──
        try:
            from agent_hina.graph import CHECKPOINT_DB_PATH
            if CHECKPOINT_DB_PATH and CHECKPOINT_DB_PATH.exists():
                import sqlite3 as _sqlite3
                ck_conn = _sqlite3.connect(str(CHECKPOINT_DB_PATH))
                ck_conn.execute("DELETE FROM writes WHERE thread_id = 'background'")
                ck_conn.execute("DELETE FROM checkpoints WHERE thread_id = 'background'")
                ck_conn.commit()
                ck_conn.execute("VACUUM")
                ck_conn.close()
                size_mb = CHECKPOINT_DB_PATH.stat().st_size / 1024 / 1024
                print(f"  [global-alarm] checkpoint 已清理 (background)，当前 DB: {size_mb:.1f} MB")
        except Exception as _e:
            print(f"  [global-alarm] checkpoint 清理失败: {_e}")

        if reply_text:
            # 存服务器 DB
            try:
                from sqlalchemy.orm import sessionmaker
                from server.database import engine
                from server.services.ChattingRecordsService import ChatService
                SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
                def _save():
                    db = SessionLocal()
                    try:
                        ChatService(db).send_message(0, reply_text)
                    finally:
                        db.close()
                await asyncio.to_thread(_save)
                print(f"  [global-alarm] 已存 DB: {reply_text[:50]}...")
            except Exception as e:
                print(f"  [global-alarm] DB 写入失败: {e}")
            # 极光推送（#6 修复：长度从 200 放宽到 500）
            from agent_hina.jpush import send_message_push
            ok = await send_message_push(push_text[:500])
            if ok:
                print(f"  [global-alarm] 已推送: {reply_text[:50]}...")
            else:
                print(f"  [global-alarm] ❌ 极光推送失败!")  # #5 修复：失败打日志
        else:
            # #9 修复：空回复打警告
            print(f"  [global-alarm] ⚠️ agent 产出空回复，闹钟已消耗（reason={reason}）")
    except Exception as e:
        print(f"  [global-alarm] agent 执行失败: {e}")
        traceback.print_exc()

# ═══════════════════════════════════════════════════
# API Key 鉴权中间件
# ═══════════════════════════════════════════════════
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import os

_HINA_API_KEY = os.getenv("HINA_API_KEY", "")

class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not _HINA_API_KEY:
            return await call_next(request)
        # 白名单：无需鉴权的路径
        if request.url.path in ("/docs", "/openapi.json", "/favicon.ico"):
            return await call_next(request)
        # WebSocket 升级请求走特殊路径鉴权
        if request.url.path == "/ws":
            # WebSocket 的 API Key 在 query string 或 header
            key = request.headers.get("X-API-Key") or request.query_params.get("key")
        else:
            key = request.headers.get("X-API-Key")
        if key != _HINA_API_KEY:
            # 注意：BaseHTTPMiddleware 里 raise HTTPException 不会被转成 403 响应，
            # 会直接抛穿导致 500，必须手动返回 JSONResponse
            return JSONResponse(status_code=403, content={"code": 403, "message": "Invalid API Key", "data": None})
        return await call_next(request)

app.add_middleware(ApiKeyMiddleware)

# CORS 中间件（移动端 App 不受 CORS 限制；带通配符时不允许 credentials，避免浏览器拦截）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册所有 REST 路由 ──
app.include_router(chat_router)        # /chat/*
app.include_router(im_router)          # /im/*
app.include_router(hina_diary_router)  # /diary/hina/*
app.include_router(me_diary_router)    # /diary/me/*
app.include_router(kaomoji_router)     # /kaomoji/*
app.include_router(photo_router)       # /photo/*
app.include_router(context_router)    # /context/*


# ═══════════════════════════════════════════════════
# WebSocket —— 日奈 AI 通信入口
# ═══════════════════════════════════════════════════

from server.ws_handler import (
    parse_user_message,
    build_state_input,
    extract_agent_reply,
    send_reply,
    save_user_message,
    read_alarms_by_type,
    remove_alarm,
)


def get_mode(raw: str) -> int:
    data = json.loads(raw)
    user_text = data.get("text", raw)
    return int(user_text[0])


@app.websocket("/ws")
async def chat_ws(websocket: WebSocket):
    global CHATTING_CODE
    await websocket.accept()
    print("  [ws] accept ok", flush=True)
    session_id = websocket.headers.get("X-Session-Id", "default")
    config = {"configurable": {"thread_id": session_id}}
    graph = _GRAPH

    queue: asyncio.Queue = asyncio.Queue()
    device_reg_id: str = ""  # 极光推送设备 ID

    # ── 接收循环 ──
    async def recv_loop():
        nonlocal device_reg_id
        try:
            while True:
                raw = await websocket.receive_text()
                print(f"  [ws] recv: {raw[:100]}", flush=True)
                # 拦截设备注册消息
                try:
                    data = json.loads(raw)
                    if data.get("type") == "register":
                        device_reg_id = data.get("reg_id", "")
                        from agent_hina.jpush import set_reg_id
                        set_reg_id(device_reg_id)
                        print(f"  [ws] 设备注册: reg_id={device_reg_id}")
                        continue
                except (json.JSONDecodeError, TypeError):
                    pass
                await queue.put(("user", raw))
        except WebSocketDisconnect:
            print("  [ws] WebSocket 断开", flush=True)
            await queue.put(("quit", None))

    print(f"  [ws] 连接建立, agent={'可用' if graph else 'echo模式'}", flush=True)
    recv_task = asyncio.create_task(recv_loop())
    # 注：闹钟统一由全局 _global_alarm_loop 触发，WS 连接不再各自扫描 time-line.md，
    # 避免同一闹钟被多次触发导致重复推送（旧逻辑每连接一个 timer_loop）

    try:
        while True:
            msg_type, payload = await queue.get()
            print(f"  [ws] queue.get → msg_type={msg_type!r} payload={str(payload)[:80]!r}", flush=True)

            if msg_type == "quit":
                break

            # ── 1. 消息解析 & state 构造 ──
            chatting_code = CHATTING_CODE
            if msg_type == "user":
                parsed = parse_user_message(payload)
                user_text = parsed["user_text"]
                chatting_code = parsed["chatting_code"]
                CHATTING_CODE = chatting_code

                await save_user_message(chatting_code, user_text)

                if graph is None:
                    resp = json.dumps({
                        "text": CHATTING_MODE_STR + f"收到: {user_text}",
                        "mood": "普通", "status": "在线",
                    }, ensure_ascii=False)
                    await websocket.send_text(resp)
                    continue

                state_input = build_state_input("user", payload, user_text)
            else:
                if msg_type in ("active", "state"):
                    # 主动/状态闹钟始终走现实模式，不受上次用户聊天模式影响
                    chatting_code = 1
                state_input = build_state_input(msg_type, payload)

            if not state_input: # type: ignore
                continue

            # ── 2. 运行 agent ──
            try:
                result = await graph.ainvoke(state_input, config)  # type: ignore
                reply = extract_agent_reply(result)
                reply_text = reply["reply_text"]
                reply_mood = reply["mood"]
                reply_status = reply["status"]

                state_dump = {k: v for k, v in result.items()
                              if not k.startswith("_") and k not in ("messages", "short_session_memory", "long_session_memory")}
                print(f"  [ws] agent_result state: {json.dumps(state_dump, ensure_ascii=False, default=str)}")
            except Exception as e:
                print(f"  [ws] agent 异常: {e}")
                traceback.print_exc()
                reply_text = f"……（出了点问题: {e}）"
                reply_mood = "困惑"
                reply_status = "发呆"

            # ── 4. 发送回复 ──
            if reply_text:
                await send_reply(reply_text, reply_mood, reply_status,
                                 chatting_code, msg_type, websocket)

    finally:
        recv_task.cancel()
