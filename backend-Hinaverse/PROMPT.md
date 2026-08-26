# Hinaverse 后端开发任务书（backend-Hinaverse）

> 你是被指派给「日奈宇宙 Hinaverse」项目写后端的新 agent。
> 开工前**必须读完全部「必读资料」**，再动手。读完不允许直接问我问题，方案里已覆盖的点自己消化。

## 0. 目标（一句话）

为多用户 AI 心理陪伴 Web 服务 Hinaverse 搭建 Python 后端：**用户 / 会话 / 消息存取 + JWT 登录 + WebSocket 实时对话**，把前端从 mock 变成真闭环的地基。最终要把消息喂给已有的日奈 LangGraph 图引擎（`agent-Hinaverse/agent_hina`），**本轮只需把对接入口做成可插拔接口**，不真正接图。

## 1. 必读资料（都在你机器上，动工前先读）

| 文件 | 为什么读 |
|---|---|
| `F:\code\project\Hinaverse\agent-Hinaverse\server\app.py` | 老 FastAPI 雏形：闹钟主动消息、设备 reg_id 注册、极光推送调用模式。**参考其模式，不是照抄** |
| `F:\code\project\Hinaverse\agent-Hinaverse\server\ws_handler.py` | WS 收发、消息落库、主动消息推送模式 |
| `F:\code\project\Hinaverse\agent-Hinaverse\agent_hina\jpush.py` | 极光推送工具（`send_push` / `send_message_push` / `set_reg_id`），本轮做成可复用通道模块 |
| `F:\code\project\Hinaverse\frontend-Hinaverse\src\stores\auth.ts` | 前端登录协议：**localStorage key 必须是 `hina_token`**，兼容 |
| `F:\code\project\Hinaverse\frontend-Hinaverse\src\stores\chat.ts` | 消息协议：`ChatMessage {id, role: 'user'|'hina'|'system', content, time}`，time 为 `HH:mm`，**字段名必须保持一致** |
| `F:\code\project\Hinaverse\frontend-Hinaverse\src\views\LoginView.vue`（可选） | 看前端怎么调登录/聊天，心里有数 |

## 2. 技术栈（固定，不要自己发明）

- Python 3.11+，**FastAPI + uvicorn**（全异步），WebSocket 用原生 `WebSocket`（FastAPI 自带）
- 数据库：**SQLite + SQLAlchemy 2.0 async（aiosqlite）**；必须走 ORM，方便以后平滑换 Postgres
- 认证：**JWT**（PyJWT）+ 密码 **bcrypt**
- 依赖锁进 `requirements.txt`（注明 Python 版本）
- **代码注释必须中文**，关键逻辑必须写注释（硬要求，主人偏好）

## 3. 本轮范围

### 要做

1. **用户**：`POST /api/auth/register`、`POST /api/auth/login`（返回 `{token, user}`）、`GET /api/auth/me`、`PUT /api/auth/profile`（昵称/头像/改密码）。注册时默认昵称随机生成（如「夜航者·4821」），avatar 留空（**本轮不做文件上传**，头像只存 URL 或空串）
2. **会话**：
   - `GET /api/conversations` → 列表（含 `last_message`、`unread_count`）
   - `POST /api/conversations` → 新建会话（Hina 首条消息即会话开场白，由回复接口生成）
   - `GET /api/conversations/{id}/messages` → 游标分页（`before_id` + `limit`）
   - 未读数：收到主动消息时 +1；用户打开会话读最后一条时清零
3. **WebSocket**：`ws://host/ws?token=<jwt>`，握手校验（失败返回 403 并关连接）
   - 客户端 → 服务端：`{type:"message", conversation_id, content}`
   - 服务端 → 客户端：`{type:"message", conversation_id, msg}`、`{type:"typing"}`（思考中）、`{type:"system", content}`、主动 `{type:"active", conversation_id, msg}`
   - **心跳**：服务端每 30s `ping`，60s 无响应即断开；客户端断开服务端不崩
4. **消息落库**：所有消息（含主动消息）持久化 —— **重启服务消息还在**，这是核心验收点
5. **Agent 对接层（本轮的关键抽象）**：`app/services/agent_service.py` 提供
   ```python
   async def generate_reply(user_message: str, user_profile: dict, history: list[dict]) -> str
   ```
   - 默认实现 = mock 温和回复（文风参考前端 `ChatWindow.vue` 里的 mockReplies：温柔、不说教、短句）
   - 注释里说明：真实接入时调 `agent-Hinaverse/agent_hina`（LangGraph，多用户并发与 LLM 耗时注意），**只能换这一个服务文件**
6. **推送通道抽象**：`app/services/push.py`
   - `PushChannel`：在线 WS 推送优先；离线走极光（复用 `agent_hina/jpush.py` 的实现思路，**按用户存 reg_id**，多用户）
   - 极光配置缺失时**静默降级**（打日志不报错）——开发期允许
   - `POST /api/device/reg_id` 注册设备（带 user 身份，JWT）
7. **开发期主动消息触发口**：`POST /api/dev/active {conversation_id}`（仅超级用户/管理员可调，或开放也行但要注释清楚），主动跑一次回复生成并走推送通道，证明链路通

### 不做（本轮禁止）

- ❌ 不 import `agent-Hinaverse` 的任何代码（图引擎接法只停留在 `agent_service` 的注释约定）
- ❌ 不动前端一行代码（前端对齐是后续独立任务）
- ❌ 不做部署 / Docker / 迁移脚本（下一轮）
- ❌ 不做 AgentMemory / TencentDB 集成（那是 v2.0.1 之后的独立任务）
- ❌ 不做管理员后台、不做支付

## 4. 建议目录结构（可微调，保持这个思路）

```
backend-Hinaverse/
  app/
    main.py            # FastAPI 实例、CORS、路由/WS 挂载、启动事件
    config.py          # 环境变量：SECRET_KEY、DB_URL、极光开关
    database.py        # async engine + session 依赖
    models.py          # User / Conversation / Message
    schemas.py         # Pydantic 请求响应模型
    security.py        # JWT 签发校验 + bcrypt
    routers/
      auth.py          # 注册/登录/me/profile
      conversations.py # 会话列表/新建/消息分页/已读
      device.py        # /api/device/reg_id
      dev.py           # /api/dev/active（开发期触发口）
    services/
      agent_service.py # 可插拔回复接口（mock 实现）
      push.py          # PushChannel：WS 优先 + 极光降级
    ws/
      ws.py            # 连接管理 + 消息分发
      protocol.py      # 消息类型常量与解析
  tests/               # 至少各 1 个用例（见验收 6）
  requirements.txt
  README.md            # 启动命令 + 接口清单
```

## 5. 协议契约（与现前端严格对齐，别改）

- token 存前端 `localStorage['hina_token']`
- 消息 JSON 字段名＝前端 chat store：`id / role / content / time`（role 枚举 `'user' | 'hina' | 'system'`）
- 用户字段：`id / nickname / avatar(jwt profile 一体时也带上 username)`
- 会话字段：`id / title / created_at / last_message / unread_count`

## 6. 完成标准（自己逐条过，全过才算 done）

1. `uvicorn app.main:app --reload` 启动无错，README 命令直接可跑
2. httpx 自测脚本：注册 → 登录 → 建会话 → 发消息 → 拉历史，全 200 且数据正确
3. **重启服务后消息还在**（SQLite 持久化）
4. WS 自测：连上、心跳、收到 `typing`+回复、断线重连服务端不崩
5. 两个 WS 客户端并发发消息，回复互不串（每客户端独立会话）
6. `pytest` 至少 4 个用例通过（auth、conversation、message分页、ws）
7. 中文注释齐全；无任何 `agent-Hinaverse` import；极光缺配置时静默降级
8. 调 `/api/dev/active` 能触发一次主动消息并落库 + 在线 WS 收到

## 7. 交付动作

- 自查全过后，汇报：目录结构、`requirements.txt`、README 摘要、自测输出样例（贴 curl/httpx 结果）
- **不要 git init / git push**，等主人审阅
- 完成后提醒主人把记忆里的 backend 状态更新