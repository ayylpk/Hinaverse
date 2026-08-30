# 日奈宇宙 · 运营台（admin-Hivaverse）

危机干预运营后台：查看心理危机事件、人工干预闭环。

## 运行

```bash
npm install
npm run dev        # 端口 5176，/api 代理到 http://localhost:8000
npm run build      # vue-tsc 类型检查 + 产物构建
```

先确保后端已启动（`backend-Hinaverse`），再访问 http://localhost:5176。

## 登录与权限

- **只有登录页，无注册入口**。登录复用后端统一账号体系：`POST /api/auth/login` → `{token, user:{..., role}}`。
- `role === "admin"` 才能进入运营台；否则提示「无运营权限」并清 token 回登录页。
- **admin 账号靠人工开通**（不提供注册/提权入口，注册永远是 `role="user"`）：

```sql
UPDATE users SET role='admin' WHERE username='xxx';
```

## 页面

- 危机事件列表：风险等级彩色标签（高危红/中危橙/低危黄）、状态文案（待人工/安抚中/已处理）、状态下拉 + 等级下拉筛选、刷新。
- 事件详情抽屉：事件全字段 + 高危摘要 + 该会话最近 20 条对话（只读）+ 标记干预结果（提交后状态置为「已处理」）。

## 接口依赖（backend-Hinaverse）

- `GET /api/crisis`（仅 admin）：列表，支持 `status_filter` / `risk_level`
- `GET /api/crisis/{id}`（仅 admin）：详情 + 最近消息
- `POST /api/crisis/{id}/intervention`（仅 admin）：标记干预结果
- `GET /api/crisis/me`：用户端，任何登录用户可访问（运营台不用）
