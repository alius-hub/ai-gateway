# AI Gateway 看板指标与聚合表设计

## 1. 说明

本文件定义平台总览、分析看板、排行、告警阈值判断所依赖的指标体系和聚合表设计。

目标不是直接从明细日志表实时扫数据，而是通过“明细 -> 分钟聚合 -> 日聚合”的方式支撑：

- 首页总览
- 趋势图
- 排行榜
- 用量分析
- 成本分析
- 性能分析
- 告警规则判断

## 2. 设计目标

指标设计需要满足：

1. 支持平台、组织、项目、Key、模型、节点多维分析
2. 支持请求量、token、成本、性能、质量等多类指标
3. 支持日级趋势和小时级趋势
4. 支持排行榜和 TOP N 查询
5. 支持告警中心做阈值判断

## 3. 指标分层

建议指标分成四层：

## 3.1 原始明细层

数据来源：

- `request_logs`
- `usage_records`
- `security_events`
- `alert_events`
- `mcp_call_logs`

特点：

- 粒度最细
- 用于审计和问题回溯
- 不直接作为首页和大盘查询来源

## 3.2 分钟聚合层

用途：

- 最近 1 小时到 24 小时趋势图
- 秒级或分钟级告警计算
- 节点实时监控

## 3.3 小时聚合层

用途：

- 最近 7 天趋势图
- 成本和性能分析

## 3.4 日聚合层

用途：

- 首页总览
- 排行榜
- 周月趋势
- 长周期报表

## 4. 维度设计

建议统一支持以下核心维度：

- 平台
- 组织
- 项目
- API Key
- 用户
- 供应商
- 模型
- 节点
- 模型类型
- 时间

说明：

- 平台级聚合适合首页和全局看板
- 项目级聚合适合业务运营和配额管理
- 节点级聚合适合容量规划和运维告警

## 5. 指标分类

## 5.1 流量指标

- `request_count`
- `success_count`
- `error_count`
- `success_rate`
- `fallback_count`
- `blocked_count`

## 5.2 Token 与资源量指标

### 对 `llm` / `vlm` / `embedding` / `rerank`

- `input_tokens`
- `output_tokens`
- `total_tokens`

### 对 `ocr`

- `ocr_image_count`
- `ocr_page_count`
- `ocr_file_bytes`

### 对 `text_to_image`

- `generated_image_count`
- `generated_pixel_level`

## 5.3 成本指标

- `estimated_cost`
- `cost_by_provider`
- `cost_by_model`
- `cost_by_project`

## 5.4 性能指标

- `avg_latency_ms`
- `p95_latency_ms`
- `p99_latency_ms`
- `avg_ttft_ms`
- `p95_ttft_ms`
- `avg_tpot_ms`
- `avg_tokens_per_second`

## 5.5 质量指标

- `provider_error_rate`
- `timeout_rate`
- `node_unavailable_rate`
- `circuit_open_count`
- `degraded_node_count`

## 5.6 安全指标

- `security_block_count`
- `prompt_block_count`
- `ip_reject_count`
- `sensitive_hit_count`

## 6. 首页总览指标设计

首页总览建议以“今天 / 近 7 天 / 近 30 天”为主要时间范围。

## 6.1 卡片指标

建议包含：

- 总请求数
- 总 token
- 总成本
- 组织数
- 项目数
- Key 数
- 模型数
- 节点数
- 当前异常节点数
- 当前未恢复告警数

## 6.2 趋势图指标

建议支持：

- 请求趋势
- token 趋势
- 成本趋势
- 成功率趋势
- 错误率趋势

## 6.3 排行榜

建议支持：

- 项目调用量 TOP N
- API Key 调用量 TOP N
- 用户调用量 TOP N
- 模型调用量 TOP N
- 节点调用量 TOP N
- 成本 TOP N

## 7. 分析看板设计

## 7.1 用量分析

支持维度：

- 按组织
- 按项目
- 按 Key
- 按模型
- 按节点

核心指标：

- 请求数
- token
- 成本
- 成功率

## 7.2 成本分析

支持维度：

- 按供应商
- 按模型
- 按项目
- 按组织

核心图表：

- 成本趋势图
- 成本占比饼图
- 成本排行榜

## 7.3 性能分析

支持维度：

- 按节点
- 按模型
- 按供应商

核心指标：

- 平均耗时
- P95 / P99 耗时
- TTFT
- TPOT
- token/s

## 7.4 质量分析

支持维度：

- 按节点
- 按供应商
- 按模型

核心指标：

- 成功率
- fallback 次数
- 节点熔断次数
- 错误率

## 7.5 安全分析

支持维度：

- 按组织
- 按项目
- 按规则

核心指标：

- 拦截次数
- 命中规则数
- 拦截来源分布

## 8. 聚合表设计建议

数据库文档已经预留了聚合统计方向，这里把它细化成推荐表。

## 8.1 平台聚合表

### `platform_minute_stats`

用于：

- 首页近实时趋势
- 快速告警判断

建议字段：

- `stat_minute`
- `request_count`
- `success_count`
- `error_count`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `estimated_cost`
- `avg_latency_ms`
- `p95_latency_ms`
- `avg_ttft_ms`
- `alert_count`

### `platform_daily_stats`

用于：

- 首页卡片
- 日趋势
- 平台报表

## 8.2 组织聚合表

### `organization_daily_stats`

建议字段：

- `organization_id`
- `stat_date`
- `request_count`
- `success_count`
- `error_count`
- `total_tokens`
- `estimated_cost`
- `avg_latency_ms`

## 8.3 项目聚合表

### `project_minute_stats`

用于项目近实时趋势与告警。

### `project_daily_stats`

用于项目级首页、分析与排行。

## 8.4 Key 聚合表

### `api_key_daily_stats`

用于：

- Key 排行
- Key 用量详情
- Key 风险识别

建议字段：

- `api_key_id`
- `project_id`
- `organization_id`
- `stat_date`
- `request_count`
- `success_count`
- `error_count`
- `total_tokens`
- `estimated_cost`
- `last_used_at`

## 8.5 模型聚合表

### `model_daily_stats`

用于模型使用趋势和模型排行。

建议字段：

- `model_code`
- `model_type`
- `provider_id`
- `stat_date`
- `request_count`
- `success_count`
- `error_count`
- `total_tokens`
- `estimated_cost`
- `avg_latency_ms`

## 8.6 节点聚合表

### `node_minute_stats`

用于：

- 节点监控
- 运维告警
- 实时趋势

建议字段：

- `node_id`
- `provider_id`
- `model_type`
- `stat_minute`
- `request_count`
- `success_count`
- `error_count`
- `total_tokens`
- `avg_latency_ms`
- `p95_latency_ms`
- `peak_concurrency`
- `timeout_count`
- `fallback_count`

### `node_daily_stats`

用于：

- 节点容量分析
- 节点排行
- 节点稳定性分析

## 9. 指标口径定义

为了避免前后端、报表、告警中心统计口径不一致，建议统一指标定义。

## 9.1 请求数

`request_count`：

- 网关成功接收并进入处理链的请求数
- 被参数校验拒绝的请求可不计入

## 9.2 成功数

`success_count`：

- 最终返回 2xx
- 或业务语义成功

## 9.3 错误数

`error_count`：

- 最终返回 4xx / 5xx
- 或安全策略拦截

## 9.4 成功率

```text
success_rate = success_count / request_count
```

## 9.5 平均耗时

```text
avg_latency_ms = sum(latency_ms) / request_count
```

## 9.6 P95 / P99

建议通过分钟聚合或离线批处理生成，不建议实时扫明细表计算。

## 9.7 token/s

适用于流式输出模型：

```text
tokens_per_second = output_tokens / streaming_duration_seconds
```

## 9.8 TTFT

TTFT 仅适用于流式场景或首包概念明确的接口。

## 10. 聚合任务设计

## 10.1 任务类型

建议拆成三类任务：

1. 实时增量任务
2. 分钟聚合任务
3. 日结聚合任务

## 10.2 实时增量任务

触发时机：

- 请求完成后

职责：

- 快速写入 Redis 或消息队列中的统计增量
- 更新热点计数器

## 10.3 分钟聚合任务

调度周期：

- 每分钟执行一次

职责：

- 汇总 Redis 分钟级计数器
- 写入 `*_minute_stats`
- 触发实时告警判断

## 10.4 日结聚合任务

调度周期：

- 每天执行一次

职责：

- 汇总分钟或小时数据
- 写入 `*_daily_stats`
- 生成排行榜数据
- 修正成本与异常口径

## 11. 排行榜设计

## 11.1 排行类型

建议支持：

- 调用量排行
- token 排行
- 成本排行
- 错误率排行
- 节点负载排行

## 11.2 排行存储策略

一期建议：

- 日榜直接读日聚合表
- 小时榜读分钟聚合表

后续若查询频繁，可增加缓存表或 Redis ZSet。

## 12. 告警阈值与聚合关系

告警中心建议依赖聚合表和实时计数器，不直接扫明细。

建议告警判断来源：

- 分钟级请求错误率
- 分钟级超时率
- 分钟级节点并发峰值
- 日级 token 使用率
- 日级成本接近阈值

## 13. 查询接口所需输出格式建议

为了方便前端图表统一，建议趋势接口统一返回：

```json
{
  "dimensions": ["2026-08-29 10:00", "2026-08-29 10:01"],
  "series": [
    {
      "name": "request_count",
      "data": [120, 132]
    }
  ]
}
```

排行接口建议返回：

```json
{
  "items": [
    {
      "name": "project-a",
      "request_count": 10000,
      "total_tokens": 500000,
      "estimated_cost": 230.5
    }
  ]
}
```

## 14. 一期建议优先落地的聚合表

一期建议先实现以下几张：

1. `platform_daily_stats`
2. `project_daily_stats`
3. `api_key_daily_stats`
4. `model_daily_stats`
5. `node_minute_stats`
6. `node_daily_stats`

这样已经足够支撑：

- 首页总览
- 基础趋势图
- 项目 / Key / 模型 / 节点排行
- 节点告警

## 15. 与其他文档的衔接

本设计与以下文档对应：

- 架构设计：[architecture.md](file:///F:/AIGC/ai-gateway/docs/architecture.md)
- 数据库设计：[database-design.md](file:///F:/AIGC/ai-gateway/docs/database-design.md)
- 管理面 API：[admin-api-design.md](file:///F:/AIGC/ai-gateway/docs/admin-api-design.md)

后续最适合继续补的是：

- 告警规则与阈值口径设计
- 分析看板接口字段清单
- 分钟聚合与日聚合任务流程图
