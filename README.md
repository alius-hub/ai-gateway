# AI Gateway

企业级 AI 网关与模型治理平台代码框架。

## 目录结构

```text
ai-gateway/
  backend/   # FastAPI 管理面 + 网关面骨架
  frontend/  # Vue 3 + Vite 管理控制台骨架
  docs/      # 架构、数据库、API 与调度设计文档
```

## 当前已完成

- 后端 FastAPI 应用入口、CORS、健康检查
- 管理面 API 路由装配：认证、总览、组织、项目、凭证、供应商、模型、节点、路由、日志
- 网关面 API 路由装配：`/v1/models`、`/v1/chat/completions`、`/v1/embeddings`
- 核心 SQLAlchemy 实体骨架：用户、组织、项目、API Key、供应商、接入模型、节点、聚合模型、项目策略、日志、用量
- 前端 Vue 3 管理台布局、侧边菜单、业务域页面占位
- 前端 API 目录、Pinia Store、Router 基础结构

## 后端启动

```bash
cd backend
uv sync
uv run start
```

默认监听 `http://localhost:8001`，可通过 `AI_GATEWAY_APP_PORT` 覆盖。

## 前端启动

```bash
cd frontend
pnpm install
pnpm dev
```

## 环境文件规则

- 后端支持：`backend/.env.dev`、`backend/.env.uat`、`backend/.env.prd`
- 前端支持：`frontend/.env.dev`、`frontend/.env.uat`、`frontend/.env.prd`
- 统一通过环境变量 `ENV` 选择配置文件，支持值：`dev`、`uat`、`prd`
- 默认使用开发环境；未设置 `ENV` 时，前后端都会自动读取 `dev` 配置

PowerShell 示例：

```powershell
$env:ENV="uat"
uv run start
```

```powershell
$env:ENV="prd"
pnpm build
```

## 下一步建议

1. 基于现有 SQLAlchemy 模型补齐成员关系、审计日志、聚合看板等后续迁移
2. 为各模块补充 `service/repository/schema` 分层
3. 将管理面占位接口替换为真实 CRUD
4. 将网关面接入真实 Provider Adapter 与节点调度逻辑
5. 补充登录鉴权、RBAC、Redis 限流和审计链路

## 数据库迁移

后端已补齐 Alembic 基础目录与初始化迁移，使用方式如下：

```bash
cd backend
uv sync
uv run alembic upgrade head
```

如需切换环境，继续沿用 `ENV` 变量：

```powershell
$env:ENV="uat"
uv run alembic upgrade head
```

开发联调时，也可以直接执行一键初始化脚本：

```powershell
cd backend
.\scripts\bootstrap_demo.ps1
```

该脚本会顺序执行：

1. 读取当前 `ENV` 对应的数据库配置
2. 执行 Alembic 迁移
3. 写入一批组织、项目、凭证、供应商、模型、节点、日志与用量演示数据
