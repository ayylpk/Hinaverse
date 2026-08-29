# 日奈 AI（agent-Hinaverse）

基于 LangGraph 构建的心理健康陪伴者 AI 核心。**不独立运行**——由 `backend-Hinaverse`（FastAPI + WebSocket）通过 `import agent_hina.*` 驱动。

## 技术栈

| 层 | 技术 |
|---|------|
| AI 引擎 | LangGraph + LangChain + DeepSeek（deepseek-v4-flash） |
| 状态持久化 | LangGraph checkpoint（SQLite，aiosqlite） |
| 工具 | Tavily 网页搜索 |

## 架构

```
用户消息 → backend WS → graph.ainvoke（thread_id=user_{uid} 多用户隔离）
  START → route_at_start
            ├─ 用户输入        → agent_think
            └─ [系统状态切换]  → daily_compress（日终，backend 定时 23:00 触发）
  agent_think ─┬─ tool_calls ──→ execute_tool ──→ 回 agent_think
               ├─ needs_human ──→ ask_human ────→ END
               └─ 直接回复       → END
```

**记忆闭环**（save/reduce 不在图内，回复返回后由 backend 异步执行）：
```
对话收尾 → save_memory（short 轻度压缩 → 追加 long）
long ≥ 3 条 → reduce_memory（中度压缩覆盖 long）
每天 23:00 → daily_compress（压缩今日 long → 明日初始上下文 + 生成给用户的日终总结）
```

**心理危机干预**（safety.py，AI 逻辑全在 agent 层）：
```
三阶段漏斗：违禁词拦截 → 关键词四维评分 → LLM 语义检测（最终定性）
高危：快速摘要（最近 10 条对话浓缩，落 high_risk_summaries 表）+ AI 持续深度安抚（引导 12356 热线）
中/低危：深度安抚模式提示词覆写
```

## 目录

```
agent_hina/
  graph.py          # 主图构建（单例，进程只 build 一次）+ 异步记忆压缩入口
  state.py          # AgentState
  models.py         # LLM 统一封装（唯一入口）
  prompts.py        # 全部提示词（主人设/记忆/澄清/安全 4 类）
  safety.py         # 三阶段漏斗安全检测 + 高危快速摘要
  tools.py          # search_web（Tavily）
  nodes/            # think / execute / ask_human / save_memory / reduce / daily_compress / routers
```

## 环境变量（.env，与 backend 共用/复用）

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API key（必填） |
| `TAVILY_API_KEY` | Tavily 网页搜索 key（可选，未配置时搜索返回失败） |

> 旧版说明（多层性格 / ChromaDB / 自主闹钟 / 每日日记 / 极光 / Android）对应已废弃功能，见 `_deprecated/`，不要恢复。
