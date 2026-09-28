# 分析看板已实现口径

入口：`/analytics/usage`、`/analytics/cost`、`/analytics/performance`。管理 API 前缀为
`/api/admin/v1`，接口分别是 `GET /analytics/usage`、`GET /analytics/cost`、
`GET /analytics/performance` 和 `GET /analytics/currencies`；仅平台管理员可访问。

三个分析接口使用相同的查询参数：

| 参数 | 说明 |
| --- | --- |
| `start_date`、`end_date` | UTC 自然日，闭区间，默认最近 7 天，最长 90 天；数据库查询使用 `[start, end + 1 天)` |
| `dimension` | 排行维度；各页面只接受该页支持的维度 |
| `scope`、`value` | 可选的单维筛选，两者必须同时提供；组织、项目、Key、供应商、接入模型使用 ID，未归属填 `none`；其他维度使用完整名称 |
| `currency` | 仅成本接口，默认 `CNY`；金额不跨币种相加 |

数据基于 `request_logs`，按**请求日志创建时间**归属日期，通过唯一的
`usage_records.request_log_id` 左关联用量。请求数包含没有用量记录的请求；
成功为最终 HTTP 2xx。排行为当前筛选范围内的前 10 项；点击排行名称可继续筛选，
可跳转带相同日期和维度条件的调用日志。

- 用量：输入、输出及总 Token 分别汇总对应非空字段，未知值不计入 Token；不存在用量记录的请求仍计入请求数。
- 成本：`estimated_cost IS NOT NULL` 才是已计价请求，金额为 0 仍属于已计价。
  “未计价”包括没有费用记录及其他币种的请求。当前网关仅对配置了 CNY
  定价的模型生成估算费用；费用不代表供应商账单。上游未返回 usage 时可能按预留量保守结算。
- 性能：平均值和连续分位数 P95/P99 只使用非空总耗时；每日 P95/P99 和每个排行项都
  从各自的实际样本计算，不平均分位数。TTFT、TPOT 仅汇总有采集值的请求。
  输出速度以 `output_tokens / (latency_ms - ttft_ms) * 1000` 逐请求计算后平均，
  要求输出 Token 大于 0 且总耗时大于 TTFT；每项单独展示有效样本数。
  失败请求也参与耗时统计，空样本显示 `-`。

首次部署需将数据库升级至 `20260928_0021`：`uv run alembic upgrade head`。
`0020` 提供 TTFT/TPOT 字段，`0021` 为常用时间及维度查询添加索引。当前时间窗内
直接聚合明细；大数据量环境应参考 `dashboard-metrics-aggregation-design.md`
引入增量日聚合，百分位仍须保留正确计算所需的分布/原始样本。
