# 日奈 AI 助手

基于 LangGraph 构建的多智能体 AI 角色扮演系统。日奈是《蔚蓝档案》中的空崎日奈，拥有完整的性格系统、记忆机制和自主意识。

## 特性

- **多层性格系统**：慵懒 → 认真 → 傲娇害羞，三层人格自然切换
- **长期记忆**：ChromaDB 向量检索（BGE-M3 Embedding），每次回复前自动检索相关记忆
- **自主意识**：定时闹钟主动发起对话，告别后自发产出关心想法
- **每日日记**：睡前自动压缩当天记忆、写日记，第二天自然接续
- **极光推送**：后台消息和日记通过 JPush 实时推送到 Android 端
- **关系演化**：自动追踪关系变化，非静态角色扮演

## 技术栈

| 层 | 技术 |
|---|------|
| AI 引擎 | LangGraph + LangChain + DeepSeek v4 |
| 记忆系统 | ChromaDB + 硅基流动 BGE-M3 Embedding |
| 后端服务 | FastAPI + WebSocket + SQLAlchemy |
| 推送 | 极光推送 (JPush) |
| Android | Java + Room + OkHttp |

## 快速开始

> 环境要求：Python 3.12+（Docker 镜像基于 3.12-slim）

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 .env（项目不内置 .env.example，直接创建，必需变量见下表）
cp .env.example .env  # 若无此文件，手动新建 .env 并填入下表变量

# 启动服务
python run.py
```

## 项目结构

```
├── agent_hina/       # AI 核心：graph、nodes、subgraphs
├── server/           # FastAPI 服务：REST + WebSocket
├── data/             # 运行时数据（chroma/sqlite/photo/daily）
├── run.py            # 入口
└── requirements.txt
```

## 架构

```
用户消息 → WebSocket → agent_think（LLM决策）
                         ├─ 搜网页
                         ├─ 需确认 → 暂停等用户
                         ├─ 需记忆 → load_memory → 重新思考
                         └─ 结束 → save_memory → spontaneous_thought
                                                         │
                                          ┌──────────────┘
                                          ▼
                                    睡前日记 → 记忆压缩 → 闹钟设定
                                          │
                                    极光推送 → Android 通知栏 → Room
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | DeepSeek API |
| `SILICONFLOW_API_KEY` | 硅基流动 Embedding |
| `TAVILY_API_KEY` | 网页搜索 |
| `JPUSH_APP_KEY` | 极光推送 AppKey |
| `JPUSH_MASTER_SECRET` | 极光推送 Master Secret |
