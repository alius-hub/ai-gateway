# AI Gateway 管理面 API 设计

## 1. 说明

本文件定义管理后台使用的管理面 API，主要服务于前端控制台，覆盖总览、用户与权限、组织、项目、凭证、模型治理、安全、日志、告警、MCP 等模块。

管理面 API 建议统一前缀：

```text
/api/admin/v1
```

## 2. 设计原则

### 2.1 接口风格

- 采用 REST 风格为主
- 列表查询使用 `GET`
- 创建使用 `POST`
- 更新使用 `PUT` 或 `PATCH`
- 删除使用 `DELETE`

### 2.2 认证方式

- 管理面使用用户登录态访问
- 建议使用 `Authorization: Bearer <jwt>`
- 所有接口都必须经过用户身份认证和资源权限校验

### 2.3 权限原则

按资源范围控制权限：

- 平台级
- 组织级
- 项目级

典型角色：

- `platform_admin`
- `org_admin`
- `project_admin`
- `member`
- `readonly`

一期权限建议：

- 管理员角色可执行创建、更新、删除、轮换、发布、绑定等写操作
- 普通用户角色仅开放只读查询接口
- 普通用户默认不开放 API Key 创建权限
- 普通用户默认不开放项目、聚合模型、节点、路由策略的修改权限

### 2.4 通用响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "request_id": "req_xxx"
}
```

分页接口建议：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [],
    "page": 1,
    "page_size": 20,
    "total": 100
  },
  "request_id": "req_xxx"
}
```

## 3. 通用查询参数约定

列表接口建议统一支持：

- `page`
- `page_size`
- `keyword`
- `status`
- `organization_id`
- `project_id`
- `start_time`
- `end_time`

## 4. 认证与用户

## 4.1 认证接口

### `POST /auth/login`

用户登录。

请求体：

```json
{
  "username": "admin",
  "password": "******"
}
```

返回：

- `access_token`
- `refresh_token`
- `user_info`

### `POST /auth/refresh`

刷新访问令牌。

### `POST /auth/logout`

用户退出登录。

### `GET /auth/me`

获取当前登录用户信息、角色和可访问资源范围。

### `GET /auth/my-projects`

查询当前用户所属项目列表。

普通用户只允许看到自己参与的项目。

### `GET /auth/my-models`

查询当前用户可见的模型列表。

建议返回两类：

- 当前用户所属项目已发布的聚合模型
- 平台级聚合模型
- 直接授权给当前用户或当前用户组的聚合模型

### `GET /auth/my-keys`

查询当前用户有权限查看的 Key 列表。

建议范围：

- 当前用户个人 Key
- 当前用户所属项目关联的项目 Key

普通用户只读，不开放创建和轮换。

## 4.2 用户管理

### `GET /users`

查询用户列表。

过滤条件建议支持：

- 用户名
- 邮箱
- 状态
- 组织

### `POST /users`

创建用户。

### `GET /users/{user_id}`

查询用户详情。

### `PATCH /users/{user_id}`

更新用户基础信息和状态。

### `GET /users/{user_id}/organizations`

查询用户所属组织列表。

### `GET /users/{user_id}/keys`

查询用户个人 Key 列表与使用情况。

### `GET /user-groups`

查询自定义用户组列表。

### `POST /user-groups`

创建独立于组织的自定义用户组，不需要 `organization_id`，也不通过用户组赋予组织角色。当前仅平台管理员可创建和管理组成员。

### `GET /user-groups/{group_id}`

查询用户组详情。

### `PATCH /user-groups/{group_id}`

更新用户组。

### `GET /user-groups/{group_id}/members`

查询用户组成员。

### `POST /user-groups/{group_id}/members`

添加用户组成员。

### `DELETE /user-groups/{group_id}/members/{user_id}`

移除用户组成员。

## 5. 组织与项目

## 5.1 组织管理

### `GET /organizations`

查询组织列表。

### `POST /organizations`

创建组织。

### `GET /organizations/{organization_id}`

查询组织详情。

### `PATCH /organizations/{organization_id}`

更新组织信息。

### `PATCH /organizations/{organization_id}/status`

启用或禁用组织。

### `GET /organizations/{organization_id}/members`

查询组织成员列表。

### `POST /organizations/{organization_id}/members`

邀请或添加组织成员。

### `PATCH /organizations/{organization_id}/members/{user_id}`

更新组织成员角色或状态。

### `DELETE /organizations/{organization_id}/members/{user_id}`

移除组织成员。

## 5.2 项目管理

### `GET /projects`

查询项目列表。

### `POST /projects`

创建项目。

请求体建议包含：

- `name`
- `code`
- `environment`
- `description`
- `owner_user_id`（可选；默认创建者）
- `organization_id`（可选；不传或传 `null` 创建平台级项目，仅平台管理员可创建；传有效组织 ID 则创建组织级项目）

平台级项目不继承组织权限：负责人和启用的项目成员可查看，负责人和项目管理员可维护；新增成员无需先加入组织。组织级项目继续校验组织权限及负责人、成员的组织成员资格。`GET /projects?scope=platform` 仅查询平台级项目；`organization_id` 和 `scope=platform` 不可同时传入。项目创建后不能修改 `organization_id`。

当前凭证、调用日志和用量等下游数据仍要求组织 ID；平台级项目在此阶段仅支持项目及成员管理，不代表已支持无组织项目的完整网关调用链路。

### `GET /projects/{project_id}`

查询项目详情。

### `PATCH /projects/{project_id}`

更新项目信息。

### `PATCH /projects/{project_id}/status`

启用或禁用项目。

### `GET /projects/{project_id}/members`

查询项目成员列表。

### `POST /projects/{project_id}/members`

添加项目成员。

### `PATCH /projects/{project_id}/members/{user_id}`

更新项目成员角色。

### `DELETE /projects/{project_id}/members/{user_id}`

移除项目成员。

## 6. 总览与分析

## 6.1 平台总览

### `GET /overview/summary`

获取首页总览卡片。

建议返回：

- 总请求数
- 总 token
- 总成本
- 组织数
- 项目数
- Key 数
- 模型数
- 节点数

### `GET /overview/trends`

获取趋势图数据。

参数建议：

- `metric`
- `granularity`
- `start_time`
- `end_time`

### `GET /overview/rankings`

获取排行榜数据。

建议支持：

- 项目排行
- Key 排行
- 用户排行
- 模型排行
- 节点排行

### `GET /overview/alerts`

获取首页异常与告警摘要。

## 6.2 分析看板

### `GET /analytics/usage`

用量分析。

### `GET /analytics/cost`

成本分析。

### `GET /analytics/performance`

性能分析。

指标建议支持：

- `latency_ms`
- `ttft_ms`
- `tpot_ms`
- `tokens_per_second`
- `success_rate`

### `GET /analytics/quality`

质量分析。

## 7. 凭证管理

## 7.1 个人 Key

### `GET /credentials/user-keys`

查询个人 Key 列表。

### `POST /credentials/user-keys`

创建个人 Key。

权限建议：

- 仅管理员可创建
- 可选 `custom_prefix`：2-20 位、字母开头，仅含字母/数字/`_`/`-`；留空使用 `agw_`。未以 `_` 结尾时生成 Key 自动加 `_` 分隔。

### `GET /credentials/user-keys/{key_id}`

查询个人 Key 详情。

### `GET /credentials/user-keys/{key_id}/secret`

仅平台管理员可再次查看已加密保存的 Key 明文及其授权模型选项，响应带
`Cache-Control: no-store`。旧 Key 仅存哈希时返回 409，需手动轮换。
常规列表、详情及编辑接口不返回明文或密文。

### `PUT /credentials/user-keys/{key_id}`

更新个人 Key 配置。

### `POST /credentials/user-keys/{key_id}/rotate`

轮换个人 Key。

权限建议：

- 仅管理员可操作
- 不传请求体时保留现有前缀；传 `{"custom_prefix": "team"}` 修改前缀，传 `{"custom_prefix": null}` 恢复默认前缀。变更前缀会使旧 Key 立即失效。

### `PATCH /credentials/user-keys/{key_id}/status`

启用或禁用个人 Key。

## 7.2 项目 Key

### `GET /credentials/project-keys`

查询项目 Key 列表。

建议过滤：

- `organization_id`
- `project_id`
- `status`

### `POST /credentials/project-keys`

创建项目 Key。

权限建议：

- 仅管理员可创建
- `custom_prefix` 的规则同个人 Key。

### `GET /credentials/project-keys/{key_id}`

查询项目 Key 详情。

### `GET /credentials/project-keys/{key_id}/secret`

同个人 Key 的管理员查看规则；仅允许读取当前作用域内的 Key。

### `PUT /credentials/project-keys/{key_id}`

更新项目 Key 配置。

### `POST /credentials/project-keys/{key_id}/rotate`

轮换项目 Key。

权限建议：

- 仅管理员可操作
- 可选 `custom_prefix`，规则同个人 Key。

### `PATCH /credentials/project-keys/{key_id}/status`

启用或禁用项目 Key。

### `GET /credentials/{key_id}/usage`

查询指定 Key 的调用量和成本统计。

## 8. 模型治理

## 8.1 供应商管理

### `GET /providers`

查询供应商列表。

### `POST /providers`

创建供应商配置。

### `GET /providers/{provider_id}`

查询供应商详情。

### `PATCH /providers/{provider_id}`

更新供应商配置。

### `PATCH /providers/{provider_id}/status`

启用或禁用供应商。

### `GET /providers/{provider_id}/health`

查询供应商健康状态和最近探活结果。

## 8.2 模型接入管理

这一层负责管理接入侧模型，不直接作为最终对外模型名称。

### `GET /access-models`

查询接入模型列表。

过滤建议：

- `model_type`
- `provider_id`
- `status`

### `POST /access-models`

创建接入模型定义。

### `GET /access-models/{access_model_id}`

查询接入模型详情。

### `PATCH /access-models/{access_model_id}`

更新接入模型定义。

## 8.3 模型出口聚合管理

这一层负责定义对外服务模型名称，并将多个接入节点聚合为一个统一出口模型。

### `GET /aggregate-models`

查询聚合模型列表。

过滤建议：

- `model_type`
- `status`
- `organization_id`

### `POST /aggregate-models`

创建聚合模型。

请求体建议包含：

- `public_model_name`
- `model_type`
- `description`
- `capabilities`
- `default_routing_strategy`

### `GET /aggregate-models/{aggregate_model_id}`

查询聚合模型详情。

### `PATCH /aggregate-models/{aggregate_model_id}`

更新聚合模型。

### `GET /aggregate-models/{aggregate_model_id}/bindings`

查询聚合模型与节点绑定关系。

### `POST /aggregate-models/{aggregate_model_id}/bindings`

新增聚合模型节点绑定。

权限建议：

- 聚合模型及其绑定关系仅管理员可配置

### `PATCH /aggregate-models/{aggregate_model_id}/bindings/{binding_id}`

更新聚合模型节点绑定。

### `DELETE /aggregate-models/{aggregate_model_id}/bindings/{binding_id}`

删除聚合模型节点绑定。

### `GET /aggregate-models/{aggregate_model_id}/permissions`

查询聚合模型下发权限列表。

建议支持按以下对象查看：

- 组织
- 项目
- 用户
- 用户组

### `POST /aggregate-models/{aggregate_model_id}/permissions`

创建聚合模型下发权限。

请求体建议包含：

- `subject_type`
- `subject_id`
- `permission_type`
- `starts_at`
- `ends_at`

### `PATCH /aggregate-models/{aggregate_model_id}/permissions/{permission_id}`

更新聚合模型下发权限。

### `DELETE /aggregate-models/{aggregate_model_id}/permissions/{permission_id}`

删除聚合模型下发权限。

## 8.4 节点管理

### `GET /nodes`

查询节点列表。

过滤建议：

- `provider_id`
- `model_type`
- `health_status`
- `status`
- `region`

### `POST /nodes`

创建节点。

请求体建议包含：

- `provider_id`
- `provider_model_id`
- `node_code`
- `node_name`
- `endpoint_url`
- `weight`
- `priority`
- `max_concurrency`
- `max_requests_per_second`
- `max_requests_per_minute`
- `max_tokens_per_minute`
- `max_tokens_per_day`
- `timeout_ms`

### `GET /nodes/{node_id}`

查询节点详情。

### `PATCH /nodes/{node_id}`

更新节点配置。

### `PATCH /nodes/{node_id}/status`

启用、禁用或摘除节点。

### `POST /nodes/{node_id}/health-check`

手动触发节点健康检查。

### `GET /nodes/{node_id}/metrics`

查询节点运行指标。

## 8.5 路由策略

### `GET /routing/policies`

查询项目模型策略列表。

### `POST /routing/policies`

创建项目模型策略。

### `GET /routing/policies/{policy_id}`

查询策略详情。

### `PATCH /routing/policies/{policy_id}`

更新策略。

### `DELETE /routing/policies/{policy_id}`

删除策略。

### `POST /routing/debug`

根据项目、模型、请求参数预演路由结果。

返回建议包括：

- 命中策略
- 候选节点
- 被过滤原因
- 最终选中节点

## 9. 配额与安全

## 9.1 配额与限流

### `GET /quota/rules`

查询配额规则。

### `POST /quota/rules`

创建配额规则。

### `PATCH /quota/rules/{rule_id}`

更新配额规则。

### `DELETE /quota/rules/{rule_id}`

删除配额规则。

### `GET /rate-limit/rules`

查询限流规则。

### `POST /rate-limit/rules`

创建限流规则。

### `PATCH /rate-limit/rules/{rule_id}`

更新限流规则。

### `DELETE /rate-limit/rules/{rule_id}`

删除限流规则。

## 9.2 安全策略

### `GET /safety/rules`

查询安全规则列表。

### `POST /safety/rules`

创建安全规则。

### `PATCH /safety/rules/{rule_id}`

更新安全规则。

### `DELETE /safety/rules/{rule_id}`

删除安全规则。

### `GET /safety/events`

查询安全事件列表。

## 10. 日志与审计

## 10.1 调用日志

### `GET /logs/requests`

查询网关调用日志。

建议过滤：

- `organization_id`
- `project_id`
- `api_key_id`
- `provider_id`
- `node_id`
- `model_type`
- `status`
- `start_time`
- `end_time`

### `GET /logs/requests/{request_id}`

查询单次调用详情。

## 10.2 审计日志

### `GET /logs/audit-events`

查询后台操作审计日志。

## 10.3 安全日志

### `GET /logs/security-events`

查询安全事件日志。

## 11. 告警中心

### `GET /alerts/rules`

查询告警规则列表。

### `POST /alerts/rules`

创建告警规则。

### `PATCH /alerts/rules/{rule_id}`

更新告警规则。

### `DELETE /alerts/rules/{rule_id}`

删除告警规则。

### `GET /alerts/events`

查询告警事件。

### `POST /alerts/events/{event_id}/ack`

确认告警。

### `POST /alerts/events/{event_id}/resolve`

手动恢复告警。

## 12. MCP 网关

### `GET /mcp/servers`

查询 MCP Server 列表。

### `POST /mcp/servers`

创建 MCP Server。

### `GET /mcp/servers/{server_id}`

查询 MCP Server 详情。

### `PATCH /mcp/servers/{server_id}`

更新 MCP Server。

### `PATCH /mcp/servers/{server_id}/status`

启用或禁用 MCP Server。

### `GET /mcp/tools`

查询 MCP Tool 列表。

### `POST /mcp/tools`

注册 MCP Tool 元数据。

### `GET /mcp/call-logs`

查询 MCP 调用日志。

## 13. 错误码建议

建议管理面统一错误码区间：

- `4001` 参数错误
- `4003` 权限不足
- `4004` 资源不存在
- `4009` 资源冲突
- `4010` 认证失效
- `4290` 访问频率过高
- `5000` 系统内部错误

## 14. 一期建议优先实现的接口

建议一期先落这些接口组：

1. `auth`
2. `organizations`
3. `projects`
4. `credentials/project-keys`
5. `providers`
6. `access-models`
7. `aggregate-models`
8. `nodes`
9. `routing/policies`
10. `logs/requests`
11. `overview/summary`

这些接口已经足够支撑一版后台控制台和基础网关治理能力。
