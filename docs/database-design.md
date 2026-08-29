# AI Gateway 数据库表结构设计

## 1. 设计目标

本设计面向企业级 AI Gateway 一期落地，重点覆盖以下能力：

- 多租户组织与项目隔离
- 用户、成员、角色权限管理
- API Key 生命周期管理
- 模型供应商与模型接入管理
- 模型出口聚合管理
- 模型接入节点管理
- 项目级模型可用策略
- 网关请求日志与用量统计
- 平台总览与聚合看板
- 安全审计与告警通知
- MCP 网关扩展能力
- 配额与限流规则配置

数据库建议使用 PostgreSQL。

## 2. 设计原则

### 2.1 多租户隔离

- 以 `organization` 作为一级租户边界
- 以 `project` 作为业务隔离与网关配置边界
- 大部分业务数据都应可追溯到 `organization_id` 和 `project_id`

### 2.2 审计优先

- 每次网关调用必须保留可审计记录
- 敏感对象如 API Key 必须支持生命周期追踪

### 2.3 扩展优先

- 模型接入与模型出口聚合独立建模
- 模型节点独立建模
- 路由策略、配额、限流策略采用独立表设计
- 为后续成本中心、审批流、告警中心保留扩展空间

## 3. 实体关系概览

核心关系如下：

1. 一个用户可以加入多个组织
2. 一个组织可以拥有多个项目
3. 一个项目可以有多个成员和多个 API Key
4. 一个供应商可以提供多个接入模型
5. 一个接入模型可以挂载多个节点
6. 一个聚合模型可以绑定多个接入节点
7. 一个项目可以配置多个聚合模型策略
8. 每条请求日志都应关联组织、项目、Key、聚合模型、节点和供应商

## 4. 核心表设计

## 4.1 users

平台用户表，用于后台登录与成员管理。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| username | varchar(64) | 用户名，唯一 |
| email | varchar(128) | 邮箱，唯一 |
| password_hash | varchar(255) | 密码哈希 |
| nickname | varchar(64) | 昵称 |
| avatar_url | varchar(255) | 头像地址 |
| phone | varchar(32) | 手机号，可空 |
| status | smallint | 状态：1 启用，0 禁用 |
| last_login_at | timestamptz | 最近登录时间 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |
| deleted_at | timestamptz | 软删除时间，可空 |

约束建议：

- `username` 唯一索引
- `email` 唯一索引

## 4.2 organizations

组织表，是一级租户边界。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| name | varchar(128) | 组织名称 |
| code | varchar(64) | 组织编码，唯一 |
| owner_user_id | bigint | 拥有者用户 ID |
| status | smallint | 状态：1 正常，0 禁用 |
| description | varchar(255) | 描述，可空 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |
| deleted_at | timestamptz | 软删除时间，可空 |

约束建议：

- `code` 唯一索引
- `owner_user_id` 外键关联 `users.id`

## 4.3 organization_members

组织成员关联表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 组织 ID |
| user_id | bigint | 用户 ID |
| role | varchar(32) | 角色，如 `org_admin`、`member`、`readonly` |
| status | smallint | 状态：1 正常，0 禁用 |
| invited_by | bigint | 邀请人 ID，可空 |
| joined_at | timestamptz | 加入时间 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(organization_id, user_id)` 唯一索引
- `organization_id` 外键
- `user_id` 外键

## 4.4 projects

项目表，是网关配置与 API Key 归属的核心边界。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 所属组织 |
| name | varchar(128) | 项目名称 |
| code | varchar(64) | 项目标识，同组织下唯一 |
| environment | varchar(32) | 环境，如 `dev`、`test`、`prod` |
| description | varchar(255) | 描述，可空 |
| status | smallint | 状态：1 正常，0 禁用 |
| owner_user_id | bigint | 项目负责人 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |
| deleted_at | timestamptz | 软删除时间，可空 |

约束建议：

- `(organization_id, code)` 唯一索引
- `organization_id` 外键
- `owner_user_id` 外键

## 4.5 project_members

项目成员关联表，用于项目级权限控制。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| project_id | bigint | 项目 ID |
| user_id | bigint | 用户 ID |
| role | varchar(32) | 角色，如 `project_admin`、`developer`、`viewer` |
| status | smallint | 状态：1 正常，0 禁用 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(project_id, user_id)` 唯一索引
- `project_id` 外键
- `user_id` 外键

## 4.6 api_keys

API Key 表，用于网关调用鉴权。

注意：明文 Key 不应直接落库，建议仅保存哈希值和前缀。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 组织 ID |
| project_id | bigint | 项目 ID，可空 |
| user_id | bigint | 用户 ID，可空，用于个人 Key |
| scope_type | varchar(32) | 作用域类型：`project`、`user` |
| name | varchar(128) | Key 名称 |
| key_prefix | varchar(32) | 展示前缀 |
| key_hash | varchar(255) | Key 哈希 |
| status | smallint | 状态：1 启用，0 禁用 |
| expires_at | timestamptz | 过期时间，可空 |
| last_used_at | timestamptz | 最后使用时间，可空 |
| last_used_ip | varchar(64) | 最后使用 IP，可空 |
| allowed_ips | jsonb | 允许 IP 列表，可空 |
| allowed_models | jsonb | 允许模型列表，可空 |
| created_by | bigint | 创建人 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |
| deleted_at | timestamptz | 软删除时间，可空 |

约束建议：

- `key_hash` 唯一索引
- `project_id` 索引
- `user_id` 索引
- `organization_id` 索引

设计说明：

- 当 `scope_type = project` 时，表示项目 Key
- 当 `scope_type = user` 时，表示个人 Key
- 个人 Key 仍建议落在组织边界内，避免越权访问其他组织资源
- 一期建议所有 Key 的创建、轮换、启用、禁用都由管理员执行
- 普通用户仅允许查看自己有权限访问的 Key 信息，不开放创建权限

## 4.7 providers

模型供应商配置表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 所属组织，可空，空表示平台级 |
| name | varchar(128) | 供应商名称 |
| code | varchar(64) | 供应商编码，如 `openai`、`deepseek` |
| provider_type | varchar(64) | 类型，如 `openai_compatible`、`native` |
| base_url | varchar(255) | API 基础地址 |
| api_key_ciphertext | text | 加密后的供应商密钥 |
| extra_config | jsonb | 额外配置 |
| status | smallint | 状态：1 启用，0 禁用 |
| health_status | varchar(32) | 健康状态 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(organization_id, code)` 唯一索引

## 4.8 provider_models

接入模型表，用于描述供应商提供的原始模型定义。

这里的模型仍然属于接入侧，不直接对外暴露为最终服务名称。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| provider_id | bigint | 供应商 ID |
| access_model_code | varchar(128) | 接入模型编码，内部唯一 |
| provider_model_name | varchar(128) | 供应商实际模型名 |
| model_type | varchar(32) | 模型类型，如 `llm`、`vlm`、`embedding`、`rerank`、`ocr`、`text_to_image` |
| context_window | integer | 上下文窗口，可空 |
| max_output_tokens | integer | 最大输出 token，可空 |
| input_price | numeric(18,6) | 输入单价，可空 |
| output_price | numeric(18,6) | 输出单价，可空 |
| currency | varchar(16) | 币种 |
| status | smallint | 状态：1 启用，0 禁用 |
| metadata | jsonb | 扩展元数据 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(provider_id, provider_model_name)` 唯一索引
- `access_model_code` 普通索引

建议的模型类型枚举：

- `llm`
- `vlm`
- `embedding`
- `rerank`
- `ocr`
- `text_to_image`

## 4.9 model_nodes

模型节点表，用于描述真正可被调度和限流的接入点。

这里的“节点”可以是：

- 某个供应商的独立接入地址
- 某个自建 vLLM/推理服务实例
- 某个 OCR 服务节点
- 某个文生图服务节点

一个 `provider_model` 可以对应多个 `model_nodes`，以支持：

- 节点级并发控制
- 节点级 token 限流
- 节点级熔断与摘除
- 节点级权重路由

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| provider_id | bigint | 供应商 ID |
| provider_model_id | bigint | 供应商模型 ID |
| node_code | varchar(64) | 节点编码，唯一 |
| node_name | varchar(128) | 节点名称 |
| model_type | varchar(32) | 节点模型类型，便于调度过滤 |
| endpoint_url | varchar(255) | 节点接入地址 |
| api_path | varchar(255) | 节点接口路径，可空 |
| region | varchar(64) | 地域，可空 |
| zone | varchar(64) | 可用区，可空 |
| protocol | varchar(32) | 协议，如 `http`、`https`、`grpc` |
| status | smallint | 状态：1 启用，0 禁用 |
| health_status | varchar(32) | 健康状态，如 `healthy`、`degraded`、`down` |
| weight | integer | 路由权重 |
| priority | integer | 调度优先级，数值越小优先级越高 |
| max_concurrency | integer | 最大并发数 |
| max_requests_per_second | integer | 每秒请求上限，可空 |
| max_requests_per_minute | integer | 每分钟请求上限，可空 |
| max_tokens_per_minute | bigint | 每分钟 token 上限，可空 |
| max_tokens_per_day | bigint | 每日 token 上限，可空 |
| timeout_ms | integer | 节点超时时间 |
| circuit_breaker_status | varchar(32) | 熔断状态，如 `closed`、`open`、`half_open` |
| current_concurrency | integer | 当前并发占用，建议运行时同步到 Redis，数据库保留统计值 |
| extra_config | jsonb | 扩展配置 |
| last_health_check_at | timestamptz | 最近健康检查时间，可空 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `node_code` 唯一索引
- `(provider_model_id, status, health_status)` 联合索引
- `(provider_id, model_type)` 联合索引

说明：

- `current_concurrency` 更适合作为运行态缓存放在 Redis 中，数据库字段主要用于持久化统计或兜底
- 节点级限流建议由 Redis 实时执行，数据库负责配置存储

## 4.9.1 aggregated_models

聚合模型表，用于定义平台对外服务的统一模型名称。

这是出口侧的核心表，一个聚合模型可以把多个不同供应商、不同原始名称的节点统一聚合为一个对外模型名。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 所属组织，可空，空表示平台级聚合模型 |
| aggregate_model_code | varchar(128) | 聚合模型编码，内部唯一 |
| public_model_name | varchar(128) | 对外服务模型名称，支持自定义 |
| model_type | varchar(32) | 模型类型 |
| description | varchar(255) | 描述，可空 |
| capabilities | jsonb | 能力标签，可空 |
| status | smallint | 状态：1 启用，0 禁用 |
| default_routing_strategy | varchar(32) | 默认路由策略，如 `priority`、`weighted` |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(organization_id, public_model_name)` 唯一索引
- `aggregate_model_code` 唯一索引

设计说明：

- `public_model_name` 是网关对外暴露的模型名称
- 调用方在网关请求中的 `model` 字段，应始终传这个名称
- 平台级聚合模型可设置为所有已登录用户可见
- 组织级聚合模型默认仅对该组织下已发布的项目可见

## 4.9.2 aggregate_model_node_bindings

聚合模型与节点绑定表，用于定义一个聚合模型包含哪些接入节点。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| aggregate_model_id | bigint | 聚合模型 ID |
| node_id | bigint | 节点 ID |
| traffic_role | varchar(32) | 流量角色：`stable`、`canary`、`backup` |
| route_priority | integer | 路由优先级 |
| weight | integer | 静态权重 |
| gray_percent | numeric(5,2) | 灰度流量百分比，可空 |
| capability_tags | jsonb | 能力标签，如 `chat`、`vision`、`reasoning` |
| route_conditions | jsonb | 路由条件，如按项目、Key、请求头、时间窗口 |
| max_rps_override | integer | 绑定级每秒请求上限，可空 |
| max_rpm_override | integer | 绑定级每分钟请求上限，可空 |
| max_concurrency_override | integer | 绑定级最大并发，可空 |
| max_tpm_override | bigint | 绑定级每分钟 token 上限，可空 |
| is_enabled | boolean | 是否启用 |
| is_fallback | boolean | 是否作为 fallback 节点 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(aggregate_model_id, node_id)` 唯一索引
- `aggregate_model_id` 索引
- `node_id` 索引

设计说明：

- `traffic_role` 用于表达正式流量、灰度流量和备流量
- `weight` 仅在同一 `traffic_role`、同一优先级内生效
- `gray_percent` 主要用于 `canary` 组
- `capability_tags` 用于支持不同能力自动路由
- `route_conditions` 用于支持按项目、Key、用户、请求头、时间窗口等做灰度

推荐示例：

聚合模型 `chat-pro` 可绑定：

- 节点 A：OpenAI，`stable`，`priority=100`，`weight=70`
- 节点 B：DeepSeek，`stable`，`priority=100`，`weight=30`
- 节点 C：私有化 Qwen，`backup`，`priority=200`
- 节点 D：新供应商，`canary`，`gray_percent=5`

这个示例的含义是：

- 5% 流量进入 `canary` 组，命中节点 D
- 95% 流量进入 `stable` 组，在 A/B 间按 70/30 分流
- 当 `stable` 和 `canary` 都不可用时，再进入 `backup` 组命中 C

## 4.9.3 user_groups

自定义用户组表，用于把一批用户组织成授权对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| organization_id | bigint | 所属组织 |
| group_name | varchar(128) | 用户组名称 |
| group_code | varchar(64) | 用户组编码 |
| description | varchar(255) | 描述，可空 |
| status | smallint | 状态：1 启用，0 禁用 |
| created_by | bigint | 创建人 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(organization_id, group_code)` 唯一索引

## 4.9.4 user_group_members

用户组成员表。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| group_id | bigint | 用户组 ID |
| user_id | bigint | 用户 ID |
| created_at | timestamptz | 创建时间 |

约束建议：

- `(group_id, user_id)` 唯一索引

## 4.9.5 aggregate_model_permissions

聚合模型节点权限表，用于定义一个聚合模型可以下发给哪些对象。

这张表负责“授权范围”，不负责“具体怎么路由”。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| aggregate_model_id | bigint | 聚合模型 ID |
| subject_type | varchar(32) | 授权对象类型：`organization`、`project`、`user`、`user_group` |
| subject_id | bigint | 授权对象 ID |
| permission_type | varchar(32) | 权限类型：`visible`、`usable`、`manageable` |
| is_enabled | boolean | 是否启用 |
| starts_at | timestamptz | 生效时间，可空 |
| ends_at | timestamptz | 失效时间，可空 |
| created_by | bigint | 创建人 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(aggregate_model_id, subject_type, subject_id, permission_type)` 唯一索引
- `subject_type, subject_id` 联合索引

设计说明：

- `organization`：适合整组织发放
- `project`：适合指定项目发放
- `user`：适合指定个人用户发放
- `user_group`：适合按自定义用户组批量发放
- `visible`：允许在控制台和模型列表中看到
- `usable`：允许实际调用使用
- `manageable`：允许管理员维护关联配置

推荐权限解析顺序：

1. 先查用户直接授权
2. 再查用户组授权
3. 再查项目授权
4. 再查组织授权
5. 最后查平台默认可见模型

这样可以同时支持平台级模型、项目级模型、个人模型和用户组模型的分发。

## 4.10 project_model_policies

项目模型策略表，用于决定项目可以访问哪些聚合模型以及如何路由。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| project_id | bigint | 项目 ID |
| aggregate_model_id | bigint | 聚合模型 ID |
| public_model_name | varchar(128) | 对外暴露的模型名称 |
| model_type | varchar(32) | 模型类型 |
| is_visible | boolean | 项目是否可见 |
| node_id | bigint | 指定节点 ID，可空 |
| traffic_role_override | varchar(32) | 覆盖流量组，可空 |
| route_priority | integer | 路由优先级，数值越小优先级越高 |
| weight | integer | 权重，用于负载分配 |
| gray_percent_override | numeric(5,2) | 覆盖灰度百分比，可空 |
| required_capabilities | jsonb | 项目请求要求的能力标签 |
| preferred_capabilities | jsonb | 项目请求偏好的能力标签 |
| is_enabled | boolean | 是否启用 |
| fallback_node_id | bigint | 兜底节点 ID，可空 |
| max_requests_per_minute | integer | 模型级限流，可空 |
| max_tokens_per_day | bigint | 模型级 token 配额，可空 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(project_id, aggregate_model_id, node_id)` 唯一索引
- `project_id` 索引

设计说明：

- `is_visible` 建议仅作为项目侧附加开关使用，真正的可见性以下发权限表为准
- 如果 `node_id` 为空，则表示由网关按策略自动挑选节点
- 如果 `node_id` 有值，则表示强制路由到指定节点
- `public_model_name` 是项目最终可见的模型名称
- 项目可以覆盖聚合模型默认的流量组、权重、灰度比例
- `required_capabilities` 用于硬性筛选节点能力
- `preferred_capabilities` 用于在满足硬条件后做优先路由
- `model_type` 可用于请求入口与节点能力匹配校验
- 普通用户只能查看自己所属项目中 `is_visible = true` 的聚合模型
- 平台级聚合模型可作为默认可见模型集合提供给普通用户只读查看
- 如果聚合模型没有授权给该项目，则项目策略不应单独生效

## 4.11 quota_rules

配额规则表，用于控制组织、项目、Key 维度资源上限。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| scope_type | varchar(32) | 作用域类型：`organization`、`project`、`api_key`、`node` |
| scope_id | bigint | 作用域 ID |
| quota_type | varchar(32) | 配额类型：`requests`、`tokens`、`cost` |
| period | varchar(16) | 周期：`minute`、`hour`、`day`、`month` |
| quota_limit | numeric(18,6) | 上限值 |
| alert_threshold | numeric(18,6) | 告警阈值，可空 |
| is_enabled | boolean | 是否启用 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(scope_type, scope_id, quota_type, period)` 唯一索引

## 4.12 rate_limit_rules

限流规则表，用于控制瞬时访问频率。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| scope_type | varchar(32) | 作用域类型 |
| scope_id | bigint | 作用域 ID |
| dimension | varchar(32) | 维度，如 `request`、`token`、`concurrency` |
| limit_per_second | integer | 每秒限制，可空 |
| limit_per_minute | integer | 每分钟限制，可空 |
| burst_limit | integer | 突发阈值，可空 |
| max_concurrency | integer | 最大并发数，可空 |
| is_enabled | boolean | 是否启用 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(scope_type, scope_id, dimension)` 唯一索引

设计说明：

- 当 `scope_type = node` 且 `dimension = concurrency` 时，可用于节点级并发限制
- 节点级限流建议与 Redis 计数器结合使用

## 4.13 request_logs

请求日志表，是审计和运营分析的核心。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| request_id | varchar(64) | 请求追踪 ID，唯一 |
| organization_id | bigint | 组织 ID |
| project_id | bigint | 项目 ID |
| api_key_id | bigint | API Key ID，可空 |
| aggregate_model_id | bigint | 聚合模型 ID |
| provider_id | bigint | 供应商 ID |
| provider_model_id | bigint | 供应商模型 ID |
| node_id | bigint | 实际命中的节点 ID |
| public_model_name | varchar(128) | 对外请求模型名 |
| model_type | varchar(32) | 模型类型 |
| endpoint | varchar(128) | 请求接口 |
| request_method | varchar(16) | 请求方法 |
| requester_ip | varchar(64) | 请求 IP |
| user_agent | varchar(255) | User Agent，可空 |
| request_body | jsonb | 请求体摘要 |
| response_body | jsonb | 响应体摘要，可空 |
| http_status | integer | HTTP 状态码 |
| provider_status | varchar(32) | 供应商调用结果 |
| latency_ms | integer | 总耗时 |
| error_code | varchar(64) | 错误码，可空 |
| error_message | text | 错误信息，可空 |
| created_at | timestamptz | 创建时间 |

约束建议：

- `request_id` 唯一索引
- `(project_id, created_at)` 联合索引
- `(provider_id, created_at)` 联合索引
- `(node_id, created_at)` 联合索引

## 4.14 usage_records

用量明细表，用于统计 token、成本和调用量。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| request_log_id | bigint | 关联请求日志 |
| organization_id | bigint | 组织 ID |
| project_id | bigint | 项目 ID |
| api_key_id | bigint | API Key ID，可空 |
| aggregate_model_id | bigint | 聚合模型 ID |
| provider_id | bigint | 供应商 ID |
| provider_model_id | bigint | 供应商模型 ID |
| node_id | bigint | 节点 ID |
| model_type | varchar(32) | 模型类型 |
| input_tokens | integer | 输入 token |
| output_tokens | integer | 输出 token |
| total_tokens | integer | 总 token |
| estimated_cost | numeric(18,6) | 估算成本 |
| currency | varchar(16) | 币种 |
| usage_date | date | 用量归属日期 |
| created_at | timestamptz | 创建时间 |

约束建议：

- `request_log_id` 唯一索引
- `(project_id, usage_date)` 联合索引
- `(organization_id, usage_date)` 联合索引
- `(node_id, usage_date)` 联合索引

设计说明：

- 对于 `llm`、`vlm`、`embedding`、`rerank`，`token` 统计通常有效
- 对于 `ocr`、`text_to_image`，除 token 外，建议后续补充页面数、图片张数等扩展计量字段

## 4.15 node_usage_stats

节点用量聚合表，用于保存节点维度的周期统计，便于看板展示和容量规划。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | bigint | 主键 |
| node_id | bigint | 节点 ID |
| stat_date | date | 统计日期 |
| request_count | bigint | 请求数 |
| success_count | bigint | 成功数 |
| error_count | bigint | 错误数 |
| input_tokens | bigint | 输入 token |
| output_tokens | bigint | 输出 token |
| total_tokens | bigint | 总 token |
| peak_concurrency | integer | 峰值并发 |
| avg_latency_ms | integer | 平均耗时 |
| created_at | timestamptz | 创建时间 |
| updated_at | timestamptz | 更新时间 |

约束建议：

- `(node_id, stat_date)` 唯一索引

## 5. 推荐补充表

以下表不是一期必需，但建议在设计时预留。

## 5.1 analytics_daily_stats

聚合统计表，用于支撑平台总览、趋势图和排行榜。

建议按不同维度拆分：

- `platform_daily_stats`
- `organization_daily_stats`
- `project_daily_stats`
- `api_key_daily_stats`
- `model_daily_stats`
- `node_daily_stats`

核心指标建议包括：

- `request_count`
- `success_count`
- `error_count`
- `input_tokens`
- `output_tokens`
- `total_tokens`
- `estimated_cost`
- `avg_latency_ms`
- `peak_concurrency`

## 5.2 audit_events

记录后台管理行为，如登录、创建项目、轮换 Key、修改模型策略。

关键字段建议：

- `event_type`
- `operator_user_id`
- `organization_id`
- `project_id`
- `target_type`
- `target_id`
- `detail`
- `created_at`

## 5.3 api_key_rotate_logs

记录 Key 轮换历史，便于审计。

关键字段建议：

- `api_key_id`
- `old_key_prefix`
- `new_key_prefix`
- `rotated_by`
- `rotated_at`

## 5.4 provider_health_logs

记录供应商健康检查结果，便于后续做自动切换。

关键字段建议：

- `provider_id`
- `check_status`
- `latency_ms`
- `error_message`
- `created_at`

## 5.5 alert_rules

告警规则表，用于定义平台、组织、项目、节点级告警阈值。

关键字段建议：

- `scope_type`
- `scope_id`
- `metric_name`
- `threshold_type`
- `threshold_value`
- `window_size`
- `notify_channels`
- `is_enabled`
- `created_at`

## 5.6 alert_events

告警事件表，用于记录实际告警触发结果。

关键字段建议：

- `rule_id`
- `scope_type`
- `scope_id`
- `event_level`
- `metric_name`
- `current_value`
- `status`
- `triggered_at`
- `resolved_at`

## 5.7 security_rules

安全规则表，用于管理敏感词、IP 白名单、黑名单和拦截策略。

关键字段建议：

- `rule_type`
- `scope_type`
- `scope_id`
- `pattern`
- `action`
- `priority`
- `is_enabled`
- `created_at`

## 5.8 security_events

安全事件表，用于记录安全策略命中情况。

关键字段建议：

- `rule_id`
- `request_id`
- `organization_id`
- `project_id`
- `api_key_id`
- `event_type`
- `action_result`
- `detail`
- `created_at`

## 5.9 mcp_servers

MCP Server 配置表。

关键字段建议：

- `organization_id`
- `name`
- `code`
- `transport_type`
- `endpoint`
- `auth_type`
- `auth_config`
- `status`
- `created_at`

## 5.10 mcp_tools

MCP Tool 元数据表。

关键字段建议：

- `server_id`
- `tool_name`
- `tool_code`
- `description`
- `schema`
- `status`
- `created_at`

## 5.11 mcp_call_logs

MCP 调用日志表。

关键字段建议：

- `request_id`
- `server_id`
- `tool_id`
- `organization_id`
- `project_id`
- `api_key_id`
- `latency_ms`
- `status`
- `error_message`
- `created_at`

## 6. 索引与性能建议

### 6.1 强索引表

以下表查询频繁，需要优先做好索引：

- `api_keys`
- `projects`
- `model_nodes`
- `aggregated_models`
- `aggregate_model_node_bindings`
- `project_model_policies`
- `request_logs`
- `usage_records`
- `alert_events`
- `security_events`
- `mcp_call_logs`

### 6.2 日志表优化

`request_logs` 和 `usage_records` 未来增长会很快，建议预留以下策略：

- 按月或按周分区
- 冷热数据分层
- 归档到对象存储或分析库

### 6.3 JSON 字段使用边界

可使用 `jsonb` 的字段包括：

- `allowed_ips`
- `allowed_models`
- `extra_config`
- `metadata`
- `request_body`
- `response_body`

但不建议把核心查询字段完全塞进 `jsonb`，否则会影响治理能力和检索效率。

## 7. 安全设计建议

### 7.1 API Key 安全

- 不保存明文 Key
- 使用哈希进行校验
- 仅保存可展示前缀
- 支持软删除与轮换审计

### 7.2 供应商密钥安全

- `api_key_ciphertext` 需要服务端加密存储
- 解密操作仅在请求转发时使用
- 后台展示时不回显完整密钥

### 7.3 软删除策略

对于后台管理对象，建议尽量使用软删除：

- `organizations`
- `projects`
- `api_keys`
- `users`

这样更利于审计和恢复。

## 8. 一期建表优先级

推荐按以下顺序建表：

1. `users`
2. `organizations`
3. `organization_members`
4. `projects`
5. `project_members`
6. `api_keys`
7. `providers`
8. `provider_models`
9. `model_nodes`
10. `aggregated_models`
11. `aggregate_model_node_bindings`
12. `project_model_policies`
13. `request_logs`
14. `usage_records`
15. `quota_rules`
16. `rate_limit_rules`
17. `node_usage_stats`
18. `platform_daily_stats`
19. `project_daily_stats`
20. `audit_events`
21. `alert_rules`
22. `alert_events`
23. `security_rules`
24. `security_events`
25. `mcp_servers`
26. `mcp_tools`
27. `mcp_call_logs`

## 9. 下一步建议

完成本设计后，下一步建议继续输出：

1. 管理面 API 设计
2. 网关面 API 设计
3. 节点调度与限流策略设计
4. 看板指标与聚合表设计
5. 数据库 ER 图
6. 一期迁移脚本拆分方案

其中最值得马上继续的是“节点调度与限流策略设计”和“管理面 API 设计”，因为它们会直接决定网关核心链路和前端后台的实现边界。
