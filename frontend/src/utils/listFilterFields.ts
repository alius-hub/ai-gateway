import type { FilterField, FilterGroup } from "@/types/filter";

const status: FilterField = {
  key: "status", label: "状态", type: "select",
  options: [{ label: "启用", value: "1" }, { label: "停用", value: "0" }],
};
const id: FilterField = { key: "id", label: "ID", type: "number" };
const text = (key: string, label: string): FilterField => ({ key, label, type: "text" });
const number = (key: string, label: string): FilterField => ({ key, label, type: "number" });
const select = (key: string, label: string, options: FilterField["options"]): FilterField =>
  ({ key, label, type: "select", options });

export const listFilterFields: Record<string, FilterField[]> = {
  providers: [
    id, text("name", "名称"), text("code", "编码"), text("provider_type", "默认协议"),
    text("base_url", "默认地址"), number("secret_count", "密钥数"),
    number("protocol_count", "协议数"), status,
  ],
  protocols: [
    id, text("code", "协议编码"), text("protocol_type", "协议类型"),
    text("base_url", "基础地址"), status,
  ],
  secrets: [id, text("name", "密钥名称"), status],
  users: [
    id, text("username", "用户名"), text("email", "邮箱"), text("nickname", "昵称"),
    select("is_platform_admin", "用户权限", [
      { label: "普通用户", value: "0" }, { label: "平台管理员", value: "1" },
    ]), status,
  ],
  members: [
    id, text("username", "用户名"), text("email", "邮箱"), text("nickname", "昵称"),
    text("role", "成员角色"),
    select("member_status", "成员状态", [
      { label: "启用", value: "1" }, { label: "停用", value: "0" },
    ]),
  ],
  "user-groups": [id, text("group_name", "用户组名称"), text("group_code", "用户组编码"), status],
  organizations: [id, text("name", "名称"), text("code", "编码"), number("owner_user_id", "负责人 ID"), status],
  projects: [
    id, text("name", "名称"), text("code", "编码"),
    number("organization_id", "所属组织 ID"),
    select("environment", "环境", [
      { label: "开发", value: "dev" }, { label: "测试", value: "test" }, { label: "生产", value: "prod" },
    ]),
    number("owner_user_id", "负责人 ID"),
    { key: "amount_budget", label: "项目累计预算（人民币元）", type: "decimal" }, status,
  ],
  "user-keys": [
    id, text("name", "名称"), number("owner_id", "用户 ID"), text("key_prefix", "前缀"),
    number("tpm_limit", "TPM"), number("qps_limit", "QPS"),
    number("token_budget", "Token 额度"), { key: "amount_budget", label: "金额额度", type: "decimal" },
    select("budget_period", "额度周期", [
      { label: "周", value: "week" }, { label: "月", value: "month" },
    ]),
    select("wait_mode", "等待方式", [
      { label: "排队", value: "queue" }, { label: "阻塞", value: "block" },
    ]), status,
  ],
  "project-keys": [
    id, text("name", "名称"), number("owner_id", "项目 ID"), text("key_prefix", "前缀"),
    number("tpm_limit", "TPM"), number("qps_limit", "QPS"),
    number("token_budget", "Token 额度"), { key: "amount_budget", label: "金额额度", type: "decimal" },
    select("budget_period", "额度周期", [
      { label: "周", value: "week" }, { label: "月", value: "month" },
    ]),
    select("wait_mode", "等待方式", [
      { label: "排队", value: "queue" }, { label: "阻塞", value: "block" },
    ]), status,
  ],
  "access-models": [
    id, text("access_model_code", "平台内部模型编码"), text("provider_model_name", "上游模型名"),
    text("provider_name", "供应商"), text("model_type", "类型"),
    number("protocol_id", "协议 ID"), text("effective_base_url", "模型 Base URL"),
    number("secret_id", "密钥 ID"), text("region", "地域"),
    { key: "input_price", label: "输入价格", type: "decimal" },
    { key: "output_price", label: "输出价格", type: "decimal" },
    select("tiered_pricing", "阶梯定价", [
      { label: "是", value: "1" }, { label: "否", value: "0" },
    ]),
    number("max_concurrency", "最大并发"), number("context_window", "最大 Token 容量"), number("max_output_tokens", "最大输出 Token"),
    number("timeout_ms", "超时时间（毫秒）"), status,
  ],
  "aggregate-models": [
    id, text("public_model_name", "对外模型名"),
    text("aggregate_model_code", "聚合编码"), text("model_type", "类型"),
    text("default_routing_strategy", "路由策略"),
    number("fallback_model_id", "兜底模型 ID"), status,
  ],
  logs: [
    { key: "created_at", label: "时间", type: "date" },
    text("request_id", "请求 ID"), text("model", "模型"),
    number("organization", "组织 ID"), number("project", "项目 ID"),
    number("key", "Key ID"), number("provider", "供应商 ID"),
    number("access_model", "接入模型 ID"), text("public_model", "对外模型"),
    select("organization_unassigned", "组织未归属", [{ label: "是", value: "1" }]),
    select("project_unassigned", "项目未归属", [{ label: "是", value: "1" }]),
    select("key_unassigned", "Key 未归属", [{ label: "是", value: "1" }]),
    select("provider_unassigned", "供应商未归属", [{ label: "是", value: "1" }]),
    select("access_model_unassigned", "接入模型未归属", [{ label: "是", value: "1" }]),
    text("endpoint", "接口"), text("model_type", "模型类型"),
    text("currency", "币种"),
    { key: "estimated_cost", label: "估算费用", type: "decimal" },
    number("http_status", "状态码"), number("latency_ms", "耗时"),
    number("total_tokens", "Token"), text("error_code", "错误码"),
  ],
  "audit-events": [
    id, { key: "created_at", label: "时间", type: "date" },
    number("actor_user_id", "操作人 ID"), text("actor_username", "操作人"),
    select("action", "动作", [
      { label: "登录", value: "login" }, { label: "创建", value: "create" },
      { label: "更新", value: "update" }, { label: "删除", value: "delete" },
      { label: "轮换 Key", value: "rotate" },
      { label: "重置密码", value: "reset_password" },
    ]),
    text("resource", "资源"),
    select("method", "请求方法", [
      { label: "POST", value: "POST" }, { label: "PUT", value: "PUT" },
      { label: "PATCH", value: "PATCH" }, { label: "DELETE", value: "DELETE" },
    ]),
    text("path", "请求路径"), text("ip_address", "来源 IP"),
    number("status_code", "结果状态码"),
  ],
  history: [
    { key: "created_at", label: "时间", type: "date" },
    text("model_code", "模型"), text("source", "来源"),
    select("mode", "模式", [
      { label: "多轮对话", value: "conversation" }, { label: "原始请求", value: "raw" },
    ]),
    select("stream", "流式", [
      { label: "是", value: "1" }, { label: "否", value: "0" },
    ]),
    number("http_status", "状态码"), number("latency_ms", "耗时"),
  ],
  strategies: [
    text("code", "策略编码"), text("name", "名称"),
    text("description", "描述"), number("min_models", "最少模型数"),
  ],
};

export function matchesFilterGroup(row: Record<string, unknown>, group: FilterGroup): boolean {
  const match = (field: string, operator: string, value: string) => {
    const actual = row[field];
    if (actual === null || actual === undefined) return false;
    if (operator === "contains") return String(actual).toLowerCase().includes(value.toLowerCase());
    const left = typeof actual === "number" ? actual : String(actual).toLowerCase();
    const right = typeof actual === "number" ? Number(value) : value.toLowerCase();
    switch (operator) {
      case "eq": return left === right;
      case "ne": return left !== right;
      case "gt": return left > right;
      case "gte": return left >= right;
      case "lt": return left < right;
      case "lte": return left <= right;
      default: return false;
    }
  };
  const results = group.conditions.map((condition) =>
    match(condition.field, condition.operator, condition.value));
  return group.mode === "and" ? results.every(Boolean) : !results.length || results.some(Boolean);
}
