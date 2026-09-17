# 日奈宇宙 · Hinaverse

> 多用户 AI 心理陪伴 Web 服务 —— 在深夜里，有人为你亮着灯。

| | |
|---|---|
| 🌐 在线站点 | https://www.sorasakihina.cn |
| 📱 安卓客户端 | https://www.sorasakihina.cn/apk/hina.apk （Web 同一账号直接登录） |

用户与角色「日奈」实时对话（WebSocket），对话内容由 LangGraph 图引擎驱动：
安全漏斗检测 → 思考/工具调用 → 记忆压缩闭环；另有日记、打卡、每日主动关心推送等陪伴功能。

## 功能一览

- 💬 **实时对话** — JWT 登录 + WS 长连接，消息全程落库；流式打字机体验
- 🛡 **三阶段安全漏斗** — 违禁词 → 四维评分 → LLM 语义检测；高危输入走危机话术 + 运营台人工队列
- 🧠 **记忆闭环** — 分层记忆（L0 原文 → L1 摘要 → L2 深层摘要 → L3 画像，内建 `app/hina_memory`）+ 日终总结
- 📔 **日记 / 打卡** — 星历式记录页，手机竖排适配
- 🖥 **运营台** — 独立管理端（用户 / 会话 / 危机队列），首管理员注册码通道注册后即关闭
- 📲 **安卓壳** — Capacitor 远程壳（加载线上站点）+ 极光推送 reg_id 上报链路 + 返回键双击退出

## 架构

```
┌─ frontend (Vue3 + Pinia + Element Plus) ─┐     ┌─ admin (运营台，同栈) ─┐
└──────────┬───────────────────────────────┘     └──────────┬─────────────┘
           │ REST /api/*        WS /ws?token=               │ REST /api/admin/*
┌──────────▼─────────────────────────────────────────────────▼───────────┐
│ backend (FastAPI + SQLAlchemy 2.0 同步访问 + MySQL)                    │
│  auth / conversations / crisis / device / admin 路由                     │
│  InboundHub → _handle_message → OutboundHub（WS 收发）                  │
│  hina_memory 分层记忆（每轮入 L0，按档位压缩出画像）· jpush 推送          │
└──────┬──────────────────────────────────────────┬───────────────────────┘
       │ import agent_hina（提示词/模型唯一入口）   │ 同库 MySQL
┌──────▼──────────────┐    ┌──────────────────────▼──────────────────┐
│ agent (LangGraph)   │    │ hina_memory（backend 内建，无外部服务）  │
│  节点图 + 安全漏斗   │    │  L0→L1→L2→L3 压缩 + hm_* 表 + 画像       │
└─────────────────────┘    └─────────────────────────────────────────┘
```

分层原则：**LLM 模型实例收口在 agent 层的 `agent_hina.models`（唯一入口），backend 只做编排**（鉴权、落库、路由、推送）。
记忆压缩的提示词与调度住在 backend 的 `app/hina_memory`（它调模型也走 `agent_hina.models`，不自己发 HTTP）。

## 仓库结构

```
Hinaverse/
├── agent-Hinaverse/     # LangGraph 图引擎：人设、安全漏斗、记忆压缩、日终总结
├── backend-Hinaverse/   # FastAPI 后端：REST + WebSocket + 极光推送 + 队列扫描
├── frontend-Hinaverse/  # 用户端 Web（Vue3 + Vite，同时被安卓壳远程加载）
├── admin-Hinaverse/     # 运营台 Web（独立构建，nginx /admin/ 独立目录部署）
├── app-Hinaverse/       # Capacitor 8 安卓壳工程（appId: cn.sorasakihina.app）
├── deploy/              # 迁移/建表 SQL 等部署配套
├── Dockerfile           # 后端镜像（agent + backend 打进同一镜像）
├── docker-compose.yml   # 生产编排（宿主 3001，复用 am-mysql 的 docker 内网）
└── .env.example         # 生产环境变量模板（复制为 .env 填写，.env 不入库）
```

## 技术栈

| 层 | 选型 |
|---|---|
| AI 引擎 | Python 3.11 · LangGraph · DeepSeek（flash 档）· Tavily 搜索 |
| 后端 | FastAPI + uvicorn · SQLAlchemy 2.0 + PyMySQL（数据访问统一同步，REST 走线程池）· JWT + bcrypt · WebSocket |
| 存储 | MySQL（utf8mb4，本地开发与生产同一套）· LangGraph checkpoint（SQLite 持久卷）· 分层记忆 hm_* 表（同库） |
| 前端 | Vue 3 `<script setup>` · Pinia · Element Plus · Vite |
| 客户端 | Capacitor 8（JDK 21 编译）· 极光推送 capacitor-plugin-jpush |
| 部署 | Docker Compose · nginx（TLS 终结 + SPA 静态 + /api /ws 反代 + /apk /admin 直出） |

## 本地开发

前置：本机 MySQL（`CREATE DATABASE hinaverse CHARACTER SET utf8mb4;`），以及一个 DeepSeek API Key。

```bash
# 1) 后端
cd backend-Hinaverse
pip install -r requirements.txt
# 自建 .env（不入库），变量名见 app/config.py：MYSQL_PASSWORD / DEEPSEEK_API_KEY 等
uvicorn app.main:app --reload --port 8000

# 2) 用户端（vite 已配 /api 与 /ws 代理到 :8000）
cd ../frontend-Hinaverse
npm install && npm run dev

# 3) 运营台（同法，另起端口）
cd ../admin-Hinaverse
npm install && npm run dev
```

agent 层（`agent-Hinaverse/`）以 `sys.path` 注入被后端直接 import，不是独立服务；其提示词与 LLM 配置见 `agent-Hinaverse/README.md`。

## 生产部署（概要）

1. 服务器复用已有的 `am-mysql` 容器（AgentMemory 应用层 9/17 已下线，mysql 容器保留继续当数据库），容器挂进 `agentmemory_default` 内网按容器名直连
2. `cp .env.example .env` 逐项填写（密钥生成方式见模板内注释），`docker compose up -d --build`
3. 前端与运营台分别 `npm run build`，产物布到 `/var/www/` 下**互相独立的目录**（教训：换装 `rm -rf` 会连坐嵌套子目录）
4. nginx：站点根 → frontend dist；`/admin/` alias 运营台；`/apk/` 直出 `hina.apk`（`application/vnd.android.package-archive`，`no-cache`）；`/api` `/ws` 反代 `127.0.0.1:3001`
5. 首次上线：用 `HINA_ADMIN_INIT_CODE` 注册首个管理员，注册码通道自动永久关闭

APK 更新 = 重 build 壳工程后覆盖 `/var/www/apk/hina.apk`，站内链接不含版本号永不过时。

## 已知限制 / Roadmap

- 📴 **vivo 离线推送**：杀后台后收不到极光通知，需在极光控制台绑 vivo 厂商通道（非阻塞，站内未读不受影响）
- 🔐 TLS 证书为免费 DV，**2026-11-30 前手动续期**
- 🧩 debug.keystore（`~/.android/debug.keystore`）决定老用户能否覆盖安装，务必异地备份

## 安全说明

- `.env` / `backend-Hinaverse/.env` 等真实凭据已在 `.gitignore`，全库不入明文密钥
- 极光 appKey 属客户端内公开设计；master secret 仅存在于服务器环境变量
- 违禁词表、危机词库在 `agent-Hinaverse/agent_hina/safety.py`，改动请同步跑测试：`pytest backend-Hinaverse/tests`（46 项）
