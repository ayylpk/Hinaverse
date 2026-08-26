# Hinaverse 后端

多用户 AI 心理陪伴 Web 服务的后端：**用户 / 会话 / 消息存取 + JWT 登录 + WebSocket 实时对话**。
本轮把前端从 mock 变成真闭环的地基，Agent 对接做成可插拔接口（默认 mock 温和回复）。

## 技术栈

- Python 3.11+ / FastAPI + uvicorn（全异步）
- SQLite + SQLAlchemy 2.0 async（aiosqlite），ORM 方式方便以后换 Postgres
- JWT（PyJWT）+ bcrypt 密码哈希
- WebSocket 原生，心跳 30s ping / 60s 超时

## 快速开始

```bash
cd backend-Hinaverse
pip install -r requirements.txt

# 启动（开发期）
uvicorn app.main:app --reload --port 8000
```

启动后访问 http://localhost:8000/docs 查看 Swagger 接口文档。

## 环境变量（可选，有默认值）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HINA_SECRET_KEY` | `hinaverse-dev-secret-change-me` | JWT 签名密钥，生产务必修改 |
| `HINA_DB_URL` | `sqlite+aiosqlite:///./hina.db` | 数据库连接 |
| `HINA_CORS_ORIGINS` | `*` | 允许的前端源，逗号分隔 |
| `JPUSH_APP_KEY` / `JPUSH_MASTER_SECRET` | 空 | 极光推送，缺失时离线推送静默降级 |

## 接口清单

### 认证 `/api/auth`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/register` | 注册，返回 `{token, user}`，昵称随机生成 |
| POST | `/login` | 登录，返回 `{token, user}` |
| GET | `/me` | 当前用户信息 |
| PUT | `/profile` | 修改昵称/头像/密码 |

### 会话 `/api/conversations`
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `` | 会话列表（含 last_message、unread_count） |
| POST | `` | 新建会话（自动生成日奈开场白） |
| GET | `/{id}/messages` | 消息游标分页（`before_id` + `limit`） |
| POST | `/{id}/read` | 未读数清零 |

### 设备 `/api/device`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/reg_id` | 注册极光推送设备 ID |

### 开发调试 `/api/dev`
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/active` | 触发一次主动消息（生成→落库→推送） |

### WebSocket
- `ws://host/ws?token=<jwt>` —— 握手校验 token，失败关闭（code 4003）
- 客户端 → 服务端：`{type:"message", conversation_id, content}` / `{type:"pong"}`
- 服务端 → 客户端：`{type:"message", conversation_id, msg}` / `{type:"typing"}` / `{type:"system", content}` / `{type:"active", conversation_id, msg}` / `{type:"ping"}`
- 心跳：服务端每 30s 发 `ping`，60s 无入站消息断开

## 消息协议（与前端严格对齐）

```jsonc
// 消息字段
{ "id": 123, "role": "user" | "hina" | "system", "content": "...", "time": "HH:mm" }
```

- token 存前端 `localStorage['hina_token']`
- 所有消息持久化到 SQLite，重启服务不丢

## Agent 对接

`app/services/agent_service.py` 提供可插拔接口：

```python
async def generate_reply(user_message: str, user_profile: dict, history: list[dict]) -> str
```

默认 mock 温和回复。真实接入时**只改这一个文件**，调用 `agent-Hinaverse/agent_hina` 的 LangGraph 图即可。注意多用户并发用独立 `thread_id`，LLM 耗时不要阻塞事件循环。

## 测试

```bash
pytest -q
```

覆盖：注册登录、会话新建、消息游标分页、WebSocket 收发。
