# 网关容量改造与升级

## 请求与连接生命周期

网关鉴权、路由准备、排队后的重新鉴权及日志写入均在工作线程中执行。每个数据库阶段结束时，实体脱离 Session，关闭事务并归还连接；上游 HTTP 等待、限流等待和 SSE 输出只使用已加载的快照。日志与用量仍同步完成持久化，但数据库操作不会阻塞事件循环。

每个应用进程在 lifespan 中创建一个 HTTP 客户端和一个 Redis 客户端，应用退出时关闭。HTTP 超时仍按接入模型配置应用到每个请求。数据库连接池大小、溢出量、等待超时均可配置；数据库连接总预算应按所有实例及 worker 数量计算。

## 并发保护

环境变量及默认值见 `backend/.env.example`：

| 配置 | 默认值 | 作用范围 |
|---|---:|---|
| `AI_GATEWAY_GATEWAY_MAX_CONCURRENCY` | 100 | 每个 worker 的在途网关 POST 请求，包括限流等待和 SSE 全生命周期 |
| `AI_GATEWAY_GATEWAY_MODEL_CONCURRENCY` | 100 | 每个接入模型的全局在途上游调用，跨共享 Redis 的实例 |
| `AI_GATEWAY_GATEWAY_PROVIDER_CONCURRENCY` | 200 | 每个供应商的全局在途上游调用，跨共享 Redis 的实例 |
| `AI_GATEWAY_GATEWAY_LEASE_SECONDS` | 120 | 并发租约有效期；每三分之一周期续租 |
| `AI_GATEWAY_DATABASE_POOL_SIZE` | 5 | 每个 worker 的常驻数据库连接 |
| `AI_GATEWAY_DATABASE_MAX_OVERFLOW` | 10 | 每个 worker 可额外使用的数据库连接 |
| `AI_GATEWAY_DATABASE_POOL_TIMEOUT` | 5 | 等待数据库连接的秒数 |
| `AI_GATEWAY_HTTP_MAX_CONNECTIONS` | 200 | 每个 worker 的 HTTP 连接池上限 |
| `AI_GATEWAY_HTTP_MAX_KEEPALIVE_CONNECTIONS` | 100 | 每个 worker 的 HTTP 空闲连接上限 |
| `AI_GATEWAY_REDIS_MAX_CONNECTIONS` | 200 | 每个 worker 的 Redis 连接池上限 |

这些默认值是保护阈值，不是压测得出的稳定容量。模型和供应商阈值分别对所有模型和供应商应用；修改阈值时应同步更新全部实例。

进程入口达到上限时返回 503 `gateway_concurrency_exceeded`；模型或供应商达到上限时返回 503 `upstream_concurrency_exceeded`，尚未发送上游请求的用量预留会退回。Redis Lua 原子获取模型和供应商两个租约，失败不会占用其中一个。重试切换模型时释放上一租约，并获取新模型的租约。SSE 结束、异常或断连释放租约；进程崩溃由租约过期回收。续租失败会终止对应调用，避免继续无保护地访问上游。

Redis 状态被清空时，尚在进行的租约及用量预留不能自动重建。升级及 Redis 恢复应先排空网关请求；Redis 应配置可靠持久化及不驱逐限流状态。当前多 Key Lua 仍要求单 Redis 主节点或兼容的主从/Sentinel 接入，不支持直接使用 Redis Cluster。

## 增量预算

新增 `gateway_spend` 表，以作用域、ID、周期类型、周期起点组成主键，保存 CNY 分单位累计费用。每条有费用的用量记录与 Key 周/月累计、项目全历史累计在同一个数据库事务中提交，通过原子 upsert 避免并发更新丢失。

预算检查只查累计表，不再对用量明细按请求执行 SUM；尚未开启金额预算的 Key 也会累计费用，以支持之后开启预算或切换周/月周期。Redis 继续承担额度预留与实际费用结算，累计表为其提供持久化基线。新增 Key/时间联合索引和凭证列表作用域索引。

## 升级步骤

1. 暂停流量并排空所有旧网关实例，避免历史回填和旧版本写入重叠。
2. 在 `backend` 中使用目标环境执行 `uv run alembic upgrade head`，新增版本为 `20260930_0028`。迁移一次性从历史 CNY 用量回填项目、Key 周/月费用，并创建索引；大表需要提前评估维护窗口。
3. 使用相同数据库、Redis、加密配置启动新版本，确认健康检查后恢复流量。

代码部署前必须执行迁移。不要让旧版本在迁移完成后继续接收流量：旧版本不会维护累计表。仓库修改本身不会自动执行目标环境迁移。

## 验证

`tests/test_gateway_capacity.py` 使用单连接数据库池，分别让 20 路普通请求及 SSE 同时等待模拟上游，验证连接全部归还、独立查询可执行，且 SQL 均不在事件循环线程执行。另验证跨客户端模型/供应商并发上限、共享客户端生命周期、预算增量累计及事务回滚。真实上游配额、生产 PostgreSQL 和真实网络下的吞吐量仍需压测。
