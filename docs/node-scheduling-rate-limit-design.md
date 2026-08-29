# AI Gateway 节点调度与限流设计

## 1. 说明

本文件定义网关运行时的节点调度、限流、配额、熔断与恢复机制。

这里的“节点”是实际承载流量的模型接入点，可能对应：

- 公有云模型接入地址
- 自建推理服务实例
- OCR 服务节点
- 文生图服务节点

本设计目标是让网关在多节点、多模型类型、多层限流场景下保持：

- 可调度
- 可治理
- 可观测
- 可恢复

## 2. 设计目标

节点治理需要同时解决以下问题：

1. 如何从多个候选节点里选出最合适的节点
2. 如何控制节点并发、请求数、token 消耗
3. 如何在节点异常时自动摘除和恢复
4. 如何让不同模型类型共用统一治理框架
5. 如何把运行时状态和后台配置解耦

## 3. 核心设计原则

### 3.1 配置与运行态分离

- PostgreSQL 保存配置和长期统计
- Redis 保存运行态计数器和短周期状态

### 3.2 限流优先于转发

所有请求在真正发往上游节点前，必须先完成：

- Key 校验
- 模型权限校验
- 限流校验
- 并发校验
- 节点可用性校验

### 3.3 节点是治理最小单元

模型策略可以定义在项目级，但实际调度、并发控制、熔断和恢复都应落在节点级。

### 3.4 多层治理叠加

运行时治理建议分成四层：

1. Key 层
2. 项目层
3. 节点层
4. 组织层

## 4. 节点抽象

结合现有设计，节点的关键配置字段包括：

- `node_id`
- `provider_id`
- `provider_model_id`
- `model_type`
- `status`
- `health_status`
- `weight`
- `priority`
- `max_concurrency`
- `max_requests_per_second`
- `max_requests_per_minute`
- `max_tokens_per_minute`
- `max_tokens_per_day`
- `timeout_ms`
- `circuit_breaker_status`

运行态关键指标包括：

- 当前并发
- 当前秒级请求数
- 当前分钟请求数
- 当前分钟 token
- 当前日 token
- 连续失败次数
- 最近成功时间
- 最近失败时间

## 5. 调度总流程

建议一次请求的节点调度流程如下：

1. 根据 `api_key` 识别组织、项目、Key
2. 根据 `model` 查询项目可用策略
3. 根据 `model_type` 过滤能力不匹配节点
4. 过滤禁用节点
5. 过滤健康异常节点
6. 过滤熔断打开节点
7. 校验 Key / 项目 / 组织限流
8. 校验节点并发限制
9. 校验节点请求限流
10. 校验节点 token 限流
11. 按调度策略选择目标节点
12. 占用节点并发
13. 发起上游请求
14. 回写日志、用量和节点统计
15. 释放节点并发
16. 若失败则根据错误类型决定是否 fallback

## 6. 候选节点筛选

## 6.1 基础筛选条件

候选节点需要满足：

- 节点 `status = enabled`
- 节点 `health_status in (healthy, degraded)`
- 节点模型类型与请求模型类型一致
- 节点在当前项目策略范围内
- 节点未超过限流和配额阈值

## 6.1.1 流量组筛选

建议先按流量组筛选候选节点，再进入组内分流。

流量组建议固定三类：

- `stable`：正式流量
- `canary`：灰度流量
- `backup`：兜底流量

推荐执行顺序：

1. 先判断请求是否命中灰度条件
2. 命中则进入 `canary` 组
3. 未命中则进入 `stable` 组
4. 当前组不可用时，再进入 `backup` 组

## 6.1.2 能力筛选

除了 `model_type`，还建议按能力标签筛选节点。

建议能力标签包括：

- `chat`
- `reasoning`
- `vision`
- `function_call`
- `structured_output`
- `embedding`
- `rerank`
- `ocr`
- `image_generation`

建议筛选顺序：

1. 先筛掉不满足 `required_capabilities` 的节点
2. 再根据 `preferred_capabilities` 做加权排序

## 6.2 项目策略筛选

项目策略应至少支持：

- 指定聚合模型
- 指定固定节点
- 指定流量组覆盖
- 多节点权重分流
- fallback 节点

## 6.3 降级筛选

当主节点全部不可用时，可进入降级候选集：

- 允许的 fallback 节点
- 同类型低优先级节点
- 备用供应商节点

## 7. 调度策略

## 7.0 推荐总规则

建议运行时按以下顺序处理：

1. 根据聚合模型找到绑定节点池
2. 根据灰度规则确定流量组
3. 根据 `model_type` 和能力标签过滤节点
4. 根据优先级筛选同层节点
5. 根据动态权重做组内分流
6. 超限或异常节点自动降权或摘除
7. 当前组不可用时进入 `backup`

## 7.1 优先级优先

适用于强主备场景。

规则：

1. 先按 `priority` 从小到大排序
2. 在同优先级节点中再按其他策略选择

优点：

- 行为稳定
- 容易控制主备关系

缺点：

- 容量利用率可能不均衡

## 7.2 权重随机

适用于同能力节点分流。

规则：

- 仅在同一流量组、同优先级候选集中按 `weight` 做随机分配

优点：

- 实现简单
- 容易做灰度流量分配

## 7.3 最小负载优先

适用于节点性能差异明显场景。

建议负载分数参考：

```text
load_score =
  concurrency_ratio * 0.4 +
  rpm_ratio * 0.2 +
  token_ratio * 0.2 +
  latency_ratio * 0.2
```

其中：

- `concurrency_ratio = current_concurrency / max_concurrency`
- `rpm_ratio = current_rpm / max_requests_per_minute`
- `token_ratio = current_tpm / max_tokens_per_minute`
- `latency_ratio = avg_latency_ms / latency_baseline`

优点：

- 资源利用更均衡

缺点：

- 需要更完整的实时指标

## 7.4 推荐方案

一期建议采用：

1. 优先级优先
2. 同优先级内按权重随机
3. 当节点数较多后再引入最小负载优先

## 7.5 动态权重修正

建议不要只依赖静态 `weight`，而是采用：

```text
effective_weight = base_weight * health_factor * capacity_factor
```

其中：

- `base_weight`：后台配置权重
- `health_factor`：健康因子，健康为 1，降级可降到 0.5，异常为 0
- `capacity_factor`：容量因子，基于并发、RPM、TPM 剩余量计算

这样可以让节点在接近满载时自动降权，而不是继续硬吃流量。

## 7.6 示例：chat-pro

假设聚合模型 `chat-pro` 配置如下：

- 节点 A：OpenAI，`stable`，`priority=100`，`weight=70`
- 节点 B：DeepSeek，`stable`，`priority=100`，`weight=30`
- 节点 C：私有化 Qwen，`backup`，`priority=200`
- 节点 D：新供应商，`canary`，`gray_percent=5`

建议实际路由含义如下：

1. 先判断请求是否命中灰度
2. 命中则进入 `canary` 组，只打到节点 D
3. 未命中则进入 `stable` 组，在 A 和 B 之间按 70/30 分流
4. 若当前组不可用或全部超限，则进入 `backup` 组命中 C

如果 A 的容量因子下降，而 B 比较空闲，则实际分流会从静态 70/30 自动向 B 倾斜。

## 8. 并发控制设计

## 8.1 并发控制目标

防止单个节点被打爆，尤其是：

- 本地推理节点
- OCR 节点
- 文生图节点

## 8.2 Redis 计数器设计

建议使用 Redis 保存节点当前并发：

```text
gateway:node:{node_id}:concurrency
```

进入请求时：

1. 原子加一
2. 若超过 `max_concurrency`，立即减一并拒绝请求

请求结束时：

1. 原子减一

建议使用 Lua 脚本保证原子性。

## 8.3 泄漏保护

为防止请求异常退出导致并发计数不释放，建议：

- 给并发占用附带 TTL
- 后台任务定时扫描异常长占用
- 请求结束时显式释放

## 9. 请求数限流设计

## 9.1 限流层级

建议同时支持：

- Key 级 QPS / RPM
- 项目级 QPS / RPM
- 节点级 QPS / RPM

## 9.2 Redis Key 设计

秒级：

```text
gateway:rate:{scope_type}:{scope_id}:sec:{timestamp}
```

分钟级：

```text
gateway:rate:{scope_type}:{scope_id}:min:{yyyyMMddHHmm}
```

## 9.3 实现建议

一期可采用固定窗口或滑动窗口近似方案：

- 固定窗口实现简单
- 滑动窗口更平滑

建议：

- 秒级限流使用固定窗口
- 分钟级限流使用滑动窗口或漏桶近似

## 10. Token 限流设计

## 10.1 为什么单独做 token 限流

请求数相同，不同请求的资源消耗差异很大，尤其是：

- LLM / VLM
- embedding 批量请求
- rerank 多文档请求

所以节点治理必须引入 token 维度。

## 10.2 预估与实记双阶段

建议分两步执行：

1. 请求前预估 token
2. 响应后按实际 token 回写修正

### 请求前预估

- 对 `llm` / `vlm` 估算输入 token
- 对 `embedding` 估算批量文本 token
- 对 `rerank` 估算 query + documents token

### 响应后修正

- 记录真实输入 token
- 记录真实输出 token
- 修正分钟和日累计值

## 10.3 Redis Key 设计

分钟 token：

```text
gateway:token:{scope_type}:{scope_id}:min:{yyyyMMddHHmm}
```

日 token：

```text
gateway:token:{scope_type}:{scope_id}:day:{yyyyMMdd}
```

## 10.4 非 token 型模型计量

对于 `ocr`、`text_to_image` 等模型，建议采用“扩展资源量”概念：

- OCR：图片数、页数、文件大小
- 文生图：生成张数、分辨率等级

一期可以：

- 保留统一 token 口径为空
- 额外记录资源量指标
- 在限流层先按请求数和并发治理

## 11. 配额校验顺序

建议统一校验顺序如下：

1. Key 请求限流
2. 项目请求限流
3. 组织请求限流
4. 节点并发限制
5. 节点请求限流
6. 节点 token 限流
7. 项目 token / 成本配额
8. 组织 token / 成本配额

这样可以优先拦截最便宜的校验，减少无意义计算。

## 11.1 不同能力自动路由

不同能力的请求不应只依赖 `model_type`，还应结合能力标签自动筛选节点。

例如聚合模型 `chat-pro` 可以定义：

- `required_capabilities = ["chat"]`
- `preferred_capabilities = ["reasoning", "function_call"]`

节点能力示例：

- 节点 A：`chat`、`vision`、`function_call`
- 节点 B：`chat`、`reasoning`
- 节点 C：`chat`、`private_deploy`
- 节点 D：`chat`、`reasoning`

那么路由时可按以下方式处理：

- 普通文本对话：进入 `stable`，A/B 分流
- 强推理请求：提高 B/D 的优先级或权重
- 带图输入：只保留支持 `vision` 的节点
- 结构化输出：只保留支持 `structured_output` 的节点

这样可以在不改变对外模型名的前提下，实现不同能力自动命中更合适的节点。

## 12. 熔断与恢复机制

## 12.1 熔断触发条件

建议结合以下条件触发熔断：

- 连续请求失败次数超过阈值
- 时间窗口内错误率过高
- 上游超时率过高
- 健康检查连续失败

## 12.2 熔断状态

建议三态：

- `closed`
- `open`
- `half_open`

### `closed`

正常放流。

### `open`

节点被摘除，不参与调度。

### `half_open`

仅允许少量探测流量，观察是否恢复。

## 12.3 恢复流程

建议：

1. 熔断打开后等待冷却时间
2. 进入 `half_open`
3. 放行少量请求或主动健康检查
4. 成功则回到 `closed`
5. 失败则重新进入 `open`

## 13. fallback 设计

## 13.1 可 fallback 的错误

建议仅对以下情况执行自动切换：

- 连接失败
- 上游超时
- 节点熔断
- 供应商临时错误

## 13.2 不建议 fallback 的错误

- 请求参数非法
- 模型权限不足
- 安全策略拦截
- Key 无效
- 配额已超限

## 13.3 fallback 次数

一期建议：

- 单次请求最多 fallback 1 到 2 次

避免雪崩式重试。

## 14. 不同模型类型的治理差异

## 14.1 `llm` / `vlm`

重点治理：

- 输入输出 token
- 流式首包时间
- 输出速度
- 长连接并发

## 14.2 `embedding`

重点治理：

- 批量大小
- 输入 token
- 吞吐量

## 14.3 `rerank`

重点治理：

- 文档条数
- 输入 token
- 平均耗时

## 14.4 `ocr`

重点治理：

- 图片大小
- 页数
- 单节点并发

## 14.5 `text_to_image`

重点治理：

- 图片数量
- 分辨率
- 单任务时长
- 节点排队

## 15. 日志与指标回写

请求结束后建议回写以下数据：

### 15.1 请求日志

- `request_id`
- `node_id`
- `provider_id`
- `model_type`
- `http_status`
- `latency_ms`
- `error_code`

### 15.2 用量记录

- 输入 token
- 输出 token
- 总 token
- 成本
- 非 token 资源量

### 15.3 节点统计

- 请求数
- 成功数
- 错误数
- 峰值并发
- 平均耗时
- token 消耗

## 16. Redis Key 归纳

建议统一前缀：

```text
gateway:
```

示例：

- `gateway:node:{node_id}:concurrency`
- `gateway:rate:key:{key_id}:sec:{timestamp}`
- `gateway:rate:project:{project_id}:min:{yyyyMMddHHmm}`
- `gateway:token:node:{node_id}:min:{yyyyMMddHHmm}`
- `gateway:token:project:{project_id}:day:{yyyyMMdd}`
- `gateway:circuit:node:{node_id}`
- `gateway:health:node:{node_id}`

## 17. 一期实现建议

一期建议先做：

1. 优先级 + 权重调度
2. 节点并发限制
3. Key / 项目 / 节点请求限流
4. 节点 token 分钟级限流
5. 基础熔断
6. 单次 fallback
7. 节点指标回写

## 18. 与其他文档的衔接

本设计与以下文档对应：

- 架构设计：[architecture.md](file:///F:/AIGC/ai-gateway/docs/architecture.md)
- 数据库设计：[database-design.md](file:///F:/AIGC/ai-gateway/docs/database-design.md)
- 管理面 API：[admin-api-design.md](file:///F:/AIGC/ai-gateway/docs/admin-api-design.md)
- 网关面 API：[gateway-api-design.md](file:///F:/AIGC/ai-gateway/docs/gateway-api-design.md)

后续最适合继续补的是：

- 节点健康检查设计
- 告警规则与自动摘除联动设计
- Redis Lua 脚本细化设计
