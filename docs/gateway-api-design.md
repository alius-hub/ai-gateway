# AI Gateway 网关面 API 设计

## 1. 说明

本文件定义业务调用方访问 AI Gateway 的网关面 API，目标是为不同模型类型提供统一入口，并在统一入口后承载鉴权、限流、路由、审计、计量和安全治理。

网关面 API 建议统一前缀：

```text
/v1
```

## 2. 设计目标

网关面 API 需要同时满足以下要求：

- 尽量兼容 OpenAI 风格，降低接入成本
- 统一接入 `llm`、`vlm`、`embedding`、`rerank`、`ocr`、`text_to_image`
- 支持节点级并发、请求数、token 治理
- 支持项目级和 Key 级权限控制
- 支持流式返回
- 支持完整请求日志和用量统计

## 3. 调用链路

一次网关请求建议经过以下链路：

1. 校验 API Key
2. 识别组织、项目、Key 作用域
3. 校验模型权限
4. 校验安全规则
5. 校验项目、Key、节点限流与配额
6. 根据模型类型和路由策略选择节点
7. 转发到目标节点
8. 记录请求日志和 usage
9. 返回标准化结果

## 4. 通用约定

## 4.1 认证方式

业务调用统一使用：

```text
Authorization: Bearer <api_key>
```

也可兼容：

```text
x-api-key: <api_key>
```

Key 可使用默认 `agw_` 或管理员创建/轮换时指定的自定义前缀。网关始终通过
完整 Key 的 SHA-256 哈希鉴权，不依赖固定的前缀判断身份。

当前已实现的 `/v1/models`、`/v1/chat/completions`、`/v1/embeddings`、
`/v1/rerank`、`/v1/ocr`、`/v1/images/generations` 要求管理员创建的有效
个人或项目 Key。模型名称使用聚合模型对外名称或已授权的接入模型编码；
管理员 JWT 不可代替业务 Key。聊天接口支持 `llm`/`vlm`，其中 OpenAI
兼容协议支持文本与多模态请求，Claude/Gemini 仅支持文本聊天。聊天
`stream: true` 返回 OpenAI 风格 SSE，支持 OpenAI、Claude、Gemini
文本协议；Embeddings/Rerank/OCR/图像生成目前只支持 OpenAI 兼容路径的
非流式 JSON 转发，需供应商实际提供相应路径和响应格式。

## 4.1.1 Key 级限额与排队（已实现）

- QPS 按 UTC 自然秒、TPM 按 UTC 自然分钟计数；输入 Token 基于请求体估算，
  与 `max_tokens` 一起预留，调用成功后按上游 `usage.total_tokens` 调整。
- 对聊天与 Embeddings，成功响应缺少有效 Token usage 时返回 502，按预留量
  计费；对 Rerank/OCR/图像生成，如果供应商未返回 Token usage，则按请求估算
  量记录并用 `X-Gateway-Usage-Estimated: true` 标记。这是 Token 额度的估算，
  不是图片/页数或供应商费用计量。
- 周额度从 UTC 周一零点重置，月额度从 UTC 每月 1 日零点重置。
  上游用量若超过预留量，该次请求仍会计入并可能使余额为负，后续请求会被拒绝。
- 配置 `block` 时，速率受限请求等待最多 `max_wait_ms`，超时返回 HTTP 429；
  周/月额度不足或单次预留量超过 TPM 时直接返回 429。
- 配置 `queue` 时，受限请求返回 HTTP 202：

```json
{
  "ticket": "32-character-hex-ticket",
  "position": 1,
  "status": "waiting",
  "poll_url": "/v1/queue/<ticket>",
  "retry_after_ms": 1000
}
```

用**同一 Key** 请求 `GET /v1/queue/<ticket>` 可获取当前排队位置，票据失效
或消费后返回 404。客户端须使用原 Key、原请求体和
`X-Queue-Ticket: <ticket>` 重发原 POST；位置查询不会自动执行调用。
重试时仍未满足限额会再次收到 HTTP 202，同一个票据最长有效 `max_wait_ms`；
超过时间后需重新排队。Redis 故障时网关返回 503，不会无治理地转发请求。
周期配额的运行计数存储在 Redis；生产部署须开启持久化并禁止计数 Key 被驱逐，
否则 Redis 丢失数据后计数会从零开始。请求日志和实际用量另写入 PostgreSQL。

## 4.2 通用请求头

建议支持：

- `Authorization`
- `x-api-key`
- `x-request-id`
- `x-project-code`
- `content-type`

## 4.3 通用响应头

建议返回：

- `x-request-id`
- `x-gateway-project-id`
- `x-gateway-model`
- `x-gateway-node-id`
- `x-gateway-provider`
- `x-ratelimit-limit`
- `x-ratelimit-remaining`

## 4.4 错误响应结构

```json
{
  "error": {
    "code": "model_not_allowed",
    "message": "model is not allowed for this api key",
    "type": "permission_error",
    "request_id": "req_xxx"
  }
}
```

## 5. 模型与能力发现

## 5.1 `GET /models`

查询当前 Key 可访问的对外聚合模型与已授权的直连接入模型列表。

返回聚合模型的对外名称或直连接入模型的内部接入编码，不返回供应商原始模型名。

建议返回：

- `id`
- `object`
- `owned_by`
- `model_type`
- `capabilities`

示例：

```json
{
  "data": [
    {
      "id": "chat-pro",
      "object": "model",
      "owned_by": "ai-gateway",
      "model_type": "llm",
      "capabilities": ["chat", "stream"]
    }
  ]
}
```

## 6. LLM / VLM 接口

## 6.1 `POST /chat/completions`

统一文本生成和多模态理解入口。

适用模型类型：

- `llm`
- `vlm`

兼容 OpenAI 风格请求体：

```json
{
  "model": "chat-pro",
  "messages": [
    {
      "role": "user",
      "content": "hello"
    }
  ],
  "temperature": 0.7,
  "stream": false
}
```

多模态场景下，`messages[].content` 可包含文本和图片对象。

网关处理重点：

- 将 `model` 解析为聚合模型名称
- 校验 `model_type`
- 估算输入 token
- 选择可用节点
- 处理流式与非流式响应

## 6.2 `POST /responses`

统一响应式接口，兼容更通用的输入输出结构。

适合作为新协议主入口，便于后续承载工具调用、结构化输出和多模态。

## 7. Embedding 接口

## 7.1 `POST /embeddings`

适用模型类型：

- `embedding`

请求体示例：

```json
{
  "model": "embedding-unified",
  "input": ["text a", "text b"]
}
```

网关处理重点：

- 批量输入长度控制
- token 统计
- 节点吞吐控制

## 8. Rerank 接口

## 8.1 `POST /rerank`

适用模型类型：

- `rerank`

请求体建议：

```json
{
  "model": "rerank-unified",
  "query": "what is ai gateway",
  "documents": [
    "doc1",
    "doc2"
  ],
  "top_n": 5
}
```

返回建议：

- 文档索引
- 分数
- 排序结果

## 9. OCR 接口

## 9.1 `POST /ocr`

适用模型类型：

- `ocr`

请求体建议支持：

- 图片 URL
- base64 图片
- 文件上传引用 ID

建议请求体：

```json
{
  "model": "ocr-unified",
  "image_url": "https://example.com/a.png"
}
```

返回建议：

- 识别文本
- 结构化块信息
- 页面数
- 耗时

## 10. 文生图接口

## 10.1 `POST /images/generations`

适用模型类型：

- `text_to_image`

请求体示例：

```json
{
  "model": "image-gen-unified",
  "prompt": "a modern ai operations dashboard",
  "size": "1024x1024",
  "n": 1
}
```

返回建议：

- 图片 URL
- 任务 ID
- 生成数量
- 耗时

## 11. 可选扩展接口

视二期能力扩展，可预留：

- `POST /audio/speech`
- `POST /audio/transcriptions`
- `POST /images/edits`
- `POST /files`

## 12. 统一治理行为

## 12.1 模型权限校验

网关必须校验：

- 请求中的 `model` 是否为有效聚合模型名称
- Key 是否允许当前模型
- Key 是否允许当前模型类型
- 项目是否允许当前模型

## 12.2 限流与配额校验

建议校验顺序：

1. Key 级请求限流
2. 项目级请求限流
3. 节点级并发限制
4. 节点级 token 限流
5. 项目级配额
6. 组织级配额

## 12.3 节点选择

建议节点选择过程：

1. 根据聚合模型名称找到候选策略
2. 过滤禁用节点
3. 过滤健康异常节点
4. 过滤超过并发上限节点
5. 过滤超过 token/request 阈值节点
6. 按优先级和权重选择
7. 调用失败时执行 fallback

## 12.4 安全检查

建议在转发前执行：

- Prompt 规则校验
- IP 白名单校验
- 黑名单校验
- 敏感输入规则

对于流式输出，可选执行：

- 增量内容审查
- 输出拦截

## 13. 流式响应设计

## 13.1 SSE

建议 `chat/completions` 和 `responses` 支持 SSE。

目前只实现 `/chat/completions` 的 SSE；对 OpenAI 上游要求
`stream_options.include_usage=true`，Claude/Gemini 文本事件统一转换为
OpenAI 风格的增量 `data:` 帧。完整结束后写入 usage，再返回 `[DONE]`；
流中断时发送 `event: gateway_error`，按预留量保守计费。`/responses`
仍是设计预留，尚无对应网关接口。Claude/Gemini 多模态事件目前不支持。

响应头：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

网关职责：

- 保持上游流式输出透传
- 统一流终止格式
- 统计流式完整耗时
- 记录 TTFT、总 token、异常中断原因

## 13.2 流式日志

对于流式请求，建议记录：

- 首包时间 `ttft_ms`
- 总耗时
- 输出 token
- 流中断原因
- 命中节点

## 14. 日志与计量

## 14.1 请求日志

每次调用建议记录：

- `request_id`
- `organization_id`
- `project_id`
- `api_key_id`
- `provider_id`
- `provider_model_id`
- `node_id`
- `aggregate_model_id`
- `public_model_name`
- `model_type`
- `endpoint`
- `http_status`
- `latency_ms`
- `error_code`

## 14.2 用量计量

不同模型类型建议使用不同计量方式：

### `llm` / `vlm`

- 输入 token
- 输出 token
- 总 token
- TTFT
- TPOT
- token/s

### `embedding`

- 输入 token
- 文本条数

### `rerank`

- query 数
- document 数
- 输入 token

### `ocr`

- 图片数
- 页数
- 文件大小

### `text_to_image`

- 图片张数
- 分辨率
- 耗时

## 15. 错误码建议

建议网关面统一错误码：

- `invalid_api_key`
- `api_key_expired`
- `model_not_allowed`
- `model_type_not_allowed`
- `project_forbidden`
- `rate_limit_exceeded`
- `quota_exceeded`
- `node_concurrency_exceeded`
- `node_unavailable`
- `provider_timeout`
- `provider_error`
- `safety_blocked`
- `internal_error`

建议状态码：

- `400` 请求参数错误
- `401` 鉴权失败
- `403` 权限不足
- `404` 模型不存在
- `429` 限流或配额超限
- `500` 网关内部错误
- `502` 上游供应商错误
- `504` 上游超时

## 16. 幂等与重试建议

对于非流式请求，可选支持：

- `Idempotency-Key`

建议仅对可安全重试的场景启用自动重试，例如：

- 上游连接失败
- 上游短时超时
- 首选节点不可用且可切换 fallback

## 17. 一期建议优先实现的接口

建议一期优先支持：

1. `GET /models`
2. `POST /chat/completions`
3. `POST /embeddings`
4. `POST /rerank`
5. `POST /ocr`
6. `POST /images/generations`

如果一期希望进一步收缩，也可以先做：

1. `GET /models`
2. `POST /chat/completions`
3. `POST /embeddings`

## 18. 与管理面的边界

网关面只负责：

- 运行时鉴权
- 运行时限流
- 运行时路由
- 请求转发
- 运行日志

管理面负责：

- 用户与权限
- 组织与项目
- Key 配置
- 模型、节点、策略配置
- 告警、分析和审计查询

这条边界要尽量保持清晰，避免把后台配置接口混入网关运行时入口。
