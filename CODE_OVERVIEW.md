# Hinaverse 三端代码梳理（2026-08-29）

> 范围：agent-Hinaverse / backend-Hinaverse / frontend-Hinaverse 全部源码（约 5500 行）。
> 结论先行：**主链路完整闭环**（登录 → 会话 → WS 发消息 → 安全检测 → LangGraph 回复 → 落库推送 → 记忆压缩/回显），
> 但存在 1 个已清空的功能（违禁词拦截）和 1 处注释与代码矛盾（深度安抚触发条件），详见 §5。

---

## 1. 总体架构

```
┌─ frontend (Vue3 + Pinia) ─────────────────────────────┐
│  LoginView / HomeView / ChatWindow / ProfileDialog     │
│  stores: auth(凭证) chat(会话+消息)   api: http / ws   │
└──────────────┬─────────────────────────────────────────┘
               │ REST /api/*（vite 代理 → :8000）   WS /ws?token=
┌──────────────▼─────────────────────────────────────────┐
│ backend (FastAPI 全异步 + SQLite/SQLAlchemy2)           │
│  routers: auth / conversations / crisis / device / dev │
│  ws: InboundHub(分发) → _handle_message → OutboundHub(下发)│
│  services: agent_service(调图) / agent_memory(记忆回显) │
│  safety_service = 转发薄壳（AI 逻辑已收口到 agent 层）  │
└──────┬──────────────────┬──────────────────────────────┘
       │ import agent_hina（sys.path 注入）  │ HTTP (X-Project/X-Api-Key)
┌──────▼──────────────────┐        ┌─────────▼───────────┐
│ agent (LangGraph 单例)  │        │ AgentMemory 外部服务 │
│ 6 节点图 + 记忆闭环     │        │ (echo/portrait, 3001)│
└─────────────────────────┘        └─────────────────────┘
```

分层原则：**所有 AI 能力（LLM 调用/提示词/安全检测）收口在 agent 层，backend 只做编排**（收消息、鉴权、落库、路由、推送）。

---

## 2. agent 端（agent_hina/，~1800 行）

| 文件 | 职责 |
|---|---|
| `graph.py` | 主图构建（**单例**，进程只 build 一次）+ `run_memory_compression()` 异步压缩入口 |
| `state.py` | `AgentState`：messages / short / long 记忆 / needs_human / needs_deep_comfort 等 |
| `models.py` | LLM 统一封装 `create_model()`（deepseek-v4-flash），chat/save/reduce/ask_human 等实例 |
| `prompts.py` | 全部提示词：主人设 + 记忆 save/reduce + 澄清 + 5 个 SAFETY_*（检测/安抚/高危话术/排队/摘要） |
| `safety.py` | 三阶段漏斗安全检测（违禁词 → 四维评分 → LLM 语义）+ 高危话术 + 危机摘要 |
| `tools.py` | `search_web`（Tavily），绑定到 chat_model |
| `jpush.py` | 极光推送（agent 侧实现，backend 侧另有 push.py 重复实现） |
| `nodes/think.py` | agent_think：组 prompt → LLM → 状态提取（tool_call 优先 → regex 兜底 → 规则兜底）+ 深度安抚覆写 |
| `nodes/routers.py` | `route_at_start`（START 分发，识别 [系统状态切换] 日终压缩）+ `should_continue` |
| `nodes/execute.py` | 执行 tool_calls → ToolMessage 回图 |
| `nodes/ask_human.py` | 澄清追问（不 interrupt，生成话术即回复） |
| `nodes/save_memory.py` | 对话收尾：short 轻度压缩 → 追加 long，清空 short |
| `nodes/reduce.py` | long ≥ 3 条 → 中度压缩覆盖 |
| `nodes/daily_compress.py` | 日终：压缩今日 → 明日上下文 + 生成给用户的日终总结 `_daily_summary_text` |

**图结构（6 节点逻辑、4 个真实节点 + 2 个路由分发）**：
`START → route_at_start →(agent_think | daily_compress)`；`agent_think → should_continue →(execute_tool ⇄ agent_think | ask_human → END | END)`。

**记忆闭环（三段式）**：对话收尾 → backend 调 `run_memory_compression` → save 入 long → long≥3 reduce 覆盖 → 每天日终 daily_compress + 给用户的总结。save/reduce 不在图内，回复先返回、压缩异步跑。

**安全检测（agent 侧核心资产）**：
- ① 违禁词 → blocked（**⚠️ 词表当前为空，见 §5-A**）
- ② 四维评分（keyword 0.4 / sentiment 0.25 / urgency 0.20 / deviation 0.15，阈值 active 8.0 / passive 5.0）；`active_crisis` 或"中危词+紧迫性"→ 直接高危跳过 LLM；**高危词单独命中仍送 LLM 排除误报**（"我的猫想自杀"用例的关键）
- ③ LLM 语义检测（safety_model，15s 超时）→ 最终定性
- 兜底：LLM 异常时"有风险信号按高危 / 无信号按安全"

---

## 3. backend 端（app/，~1700 行）

| 模块 | 职责 |
|---|---|
| `main.py` | 应用入口：CORS、5 个 REST 路由 + WS 路由、启动建表 |
| `config.py` | env 配置（JWT/DB/极光/AgentMemory）；DEEPSEEK key 缺失时回退读 agent/.env |
| `database.py` | async engine + **sync engine 双轨**（WS 长连接用同步，规避事件循环绑定问题） |
| `models.py` | User / Conversation / Message / **CrisisEvent**（危机事件，带 user_id 多用户隔离）+ 消息插入工具 |
| `security.py` | bcrypt + JWT + `get_current_user` 依赖 |
| `schemas.py` | Pydantic 模型，字段与前端协议严格对齐 |
| `routers/auth.py` | 注册/登录/me/改资料（昵称随机"夜航者·4821"） |
| `routers/conversations.py` | 会话列表/新建（自动开场白）/消息游标分页/未读清零 |
| `routers/crisis.py` | 运营端危机事件列表 + 标记干预结果（**无管理员鉴权，见 §5**） |
| `routers/device.py` | 注册极光 reg_id（按用户存） |
| `routers/dev.py` | 开发调试：主动触发一次消息 |
| `ws/Hub.py` | **InboundHub**（type→handler 分发）+ **OutboundHub**（统一出口：在线 WS / 离线极光降级） |
| `ws/protocol.py` | WS 消息协议常量 |
| `ws/ws.py` | 端点：JWT 握手、心跳（30s ping/60s 超时）、`_handle_message` 主链路 |
| `ws/services/agent_service.py` | 调 LangGraph 图：懒加载单例 + `thread_id=user_{uid}` 隔离 + 回复返回后 `create_task` 异步压缩 |
| `ws/services/safety_service.py` | **纯转发薄壳**（只 re-export agent_hina.safety，无 AI 逻辑） |
| `ws/services/push.py` | 极光离线推送（PushChannel，WS 失败/离线降级） |
| `services/agent_memory.py` | AgentMemory 客户端：`echo_async`（后台 fire-and-forget + 503 指数退避）+ `get_portrait`（3s 超时返回 None） |

**WS 主链路 `_handle_message` 四分支**：
1. `blocked` → 拦截提示，不进 agent（**当前不可达，词表为空**）
2. `高危` → LLM 高危过渡话术 → 落 CrisisEvent(pending_human) + 自动摘要 → 落库 hina 消息 → 推送（不调 agent）
3. `中危` → 落 CrisisEvent(comforting) → 正常进 agent 但传 `needs_deep_comfort=True`（深度安抚覆写）
4. `安全/低危` → 正常 agent 流程

每轮用户消息 & 日奈回复都会 `echo_async` 推给 AgentMemory 记忆管线（user/ai 角色分清），与聊天无关，画像/记忆由外部服务异步消化。

---

## 4. frontend 端（src/，~2000 行）

| 模块 | 职责 |
|---|---|
| `api/http.ts` | fetch 薄封装：自动带 token、错误统一 ApiError、零依赖 |
| `api/ws.ts` | WS 客户端单例：前端版分发表 `on(type, cb)`、心跳回 pong、指数退避重连（1s→30s 封顶）、4003 不重连 |
| `stores/auth.ts` | 登录/注册/me/改资料；token+user 双写 localStorage（`hina_token`） |
| `stores/chat.ts` | **核心**：`ensureReady`（幂等：取/建会话→拉历史→连 WS）、乐观上屏、typing/system/active/message 处理、登出 reset |
| `views/HomeView.vue` | 星空主页 + 导航（资料/退出） |
| `views/LoginView.vue` | 登录/注册页（UI 为主，交互走 auth store） |
| `components/ChatWindow.vue` | 聊天窗口（消息收发全在 chat store，组件只管输入框/滚动/展示） |
| `components/ProfileDialog.vue` | 资料编辑弹窗 |
| `router/index.ts` | 路由守卫：无 token → /login；有 token 访问 login → /home |
| `vite.config.ts` | `/api` → :8000、`/ws` → ws://:8000 开发代理 |

前端不感知危机干预——高危/拦截只收到普通 message / system 消息，无需特判。

---

## 5. 发现的问题与遗留（按优先级）

**A. [高] 违禁词表被清空，第一道防线失效**
`safety.py:56` `FORBIDDEN_WORDS = []`（`_FORBIDDEN_PORN/_VIOLENCE/_POLITICAL` 列表被注释删除）。`blocked` 分支永不触发，ws.py 分支 A 与 CrisisEvent 的"违禁拦截"路径成死代码。若是有意为之（政治词风险）建议加注释说明；否则需重建词表（色情/暴力两类即可，政治类可留空）。

**B. [高] 深度安抚触发条件三处表述不一致（含未提交改动）**
- ws.py:225 实际代码：`needs_deep_comfort = safety.risk_level in ("中危")` → **只有中危触发**
- ws.py 分支 C 注释：写"中/低危 → 开启深度安抚"（与代码不符，低危不触发）
- state.py 未提交 diff：注释从"中/低危"改成"高危命中时由 backend 传入"（与实际中危逻辑矛盾）
- 建议统一口径：要么让低危也触发（符合 AGENT_TASK_PROMPT 的"中/低危深度安抚"设计），要么把注释统一成"中危"。

**C. [中] 日终压缩链路无触发端**
graph 有 daily_compress 节点 + START 分发，但 backend **没有定时任务**发 `[系统状态切换] 日终压缩`。整条日终链路（压缩 + 给用户的总结）目前是死路。若暂不做，建议在代码中标注"未接线"。

**D. [中] SAFETY_QUEUE_PROMPT 已定义未使用**
排队维持陪伴逻辑未实现（prompts 资产在，可接受，属预留）。

**E. [低] 死代码/死参数**
- `agent_service.generate_reply` 的 `history` 参数被接收但未用于图调用（ws.py/dev.py 都传了）
- `conversations.py` 顶部 `from app.ws.services.agent_service import generate_reply` 未使用
- `think.py:113` 读 `state.get("_portrait")`，但 `AgentState` 无此字段（get 有默认值不报错，属画像接入前的预留）
- `models.py` 的 `schedule_model`（定时主动消息已删）、`load_memory_model=None`（RAG 已删）

**F. [低] 两套极光推送实现重复**
`agent_hina/jpush.py` 与 `backend/app/ws/services/push.py` 逻辑几乎一致。push.py 注释称"本轮不 import agent"，但 agent_service/safety_service 早已 sys.path 注入 import agent 包，该约束已过时，可考虑二选一收敛。

**G. [低] 运营端危机接口无管理员鉴权**
`crisis.py` 列表/标记接口任何登录用户可访问（文件注释已声明，生产需加 `role=="admin"` 校验）。

**H. [低] agent README 严重过期**
README 仍描述"多层性格/ChromaDB 向量检索/自主意识/每日日记"等已删除功能，与当前 6 节点简化图不符，误导后续开发者。

---

## 6. 未提交改动

- `agent_hina/state.py`：仅注释一行改动（needs_deep_comfort 注释"中/低危"→"高危"），**与 §5-B 的代码矛盾，建议先决定语义再提交**。

---

## 7. 一条消息的完整旅程

```
用户输入 → chat.sendMessage（乐观上屏）
  → WS {type:message, conversation_id, content}
  → _handle_message：校验会话归属 → 落库用户消息 → echo_async 记忆回显
  → 安全检测 check_message（四维评分 / LLM 定性）
  → 分支：高危→过渡话术+危机事件+摘要 | 中危→CrisisEvent+深度安抚 | 安全→正常
  → send_typing → generate_reply（agent 图 ainvoke，thread=user_{uid}）
  → 落库 hina 消息 → echo_async(ai) → send_message 推送
  → 后台 asyncio.create_task：run_memory_compression（save/reduce）
```
