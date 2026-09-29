# Alembic 迁移说明

## 初始化

```bash
uv sync
```

## 执行迁移

默认读取 `backend/.env.dev`：

```bash
uv run alembic upgrade head
```

切换环境时复用现有约定：

```powershell
$env:ENV="uat"
uv run alembic upgrade head
```

## 生成新迁移

```bash
uv run alembic revision --autogenerate -m "add xxx"
```

## 当前基线范围

当前初始迁移与现有 SQLAlchemy 模型保持一致，已覆盖：

- 用户、组织、项目
- API Key
- 供应商、接入模型、节点
- 聚合模型、节点绑定、项目模型策略
- 请求日志、用量记录

文档中尚未落到代码模型的表，例如聚合看板表，建议在后续模块开发时继续追加迁移。管理操作审计日志由 `20260929_0023` 迁移创建。
