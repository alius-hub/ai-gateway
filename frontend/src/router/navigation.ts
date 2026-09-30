export type NavigationIcon =
  | "overview"
  | "models"
  | "people"
  | "keys"
  | "security"
  | "analytics"
  | "logs"
  | "alerts"
  | "mcp"
  | "settings";

export interface NavigationItem {
  label: string;
  path: string;
  description?: string;
  planned?: boolean;
}

export interface NavigationGroup {
  id: NavigationIcon;
  label: string;
  items: NavigationItem[];
}

export const navigation: NavigationGroup[] = [
  {
    id: "overview",
    label: "平台总览",
    items: [{ label: "运营总览", path: "/dashboard" }],
  },
  {
    id: "models",
    label: "模型治理",
    items: [
      { label: "供应商管理", path: "/providers" },
      { label: "模型管理", path: "/models" },
      { label: "路由策略", path: "/routing", description: "查看平台内置的固定路由策略。" },
      { label: "聚合模型", path: "/models/aggregated", description: "选择路由策略并直接配置候选接入模型。" },
      { label: "在线调试", path: "/playground", description: "调试模型对话、参数、响应耗时和 Token 用量。" },
    ],
  },
  {
    id: "people",
    label: "用户与权限",
    items: [
      { label: "用户管理", path: "/users" },
      { label: "用户组", path: "/user-groups" },
      { label: "组织管理", path: "/organizations" },
      { label: "项目管理", path: "/projects" },
    ],
  },
  {
    id: "keys",
    label: "凭证中心",
    items: [
      { label: "个人 Key", path: "/credentials/personal", description: "管理个人凭证、过期时间与访问范围。" },
      { label: "项目 Key", path: "/credentials" },
    ],
  },
  {
    id: "security",
    label: "安全中心",
    items: [
      { label: "安全策略", path: "/security/rules", planned: true, description: "管理内容安全和资源访问策略。" },
      { label: "敏感词规则", path: "/security/keywords", planned: true, description: "配置敏感内容识别与拦截规则。" },
      { label: "IP 规则", path: "/security/ip", planned: true, description: "配置访问来源和 IP 白名单。" },
      { label: "配额与限流", path: "/security/quotas", planned: true, description: "管理项目、凭证和模型的限额策略。" },
    ],
  },
  {
    id: "analytics",
    label: "分析看板",
    items: [
      { label: "用量分析", path: "/analytics/usage", description: "分析请求量、Token 消耗和使用趋势。" },
      { label: "成本分析", path: "/analytics/cost", description: "按项目、模型和供应商分析成本。" },
      { label: "性能分析", path: "/analytics/performance", description: "查看延迟、错误率和模型性能。" },
    ],
  },
  {
    id: "logs",
    label: "日志中心",
    items: [
      { label: "调用日志", path: "/logs", description: "查询网关调用、响应及用量记录。" },
      { label: "审计日志", path: "/logs/audit", description: "追踪平台配置和管理操作。" },
      { label: "安全日志", path: "/logs/security", planned: true, description: "查询安全策略命中和拦截事件。" },
    ],
  },
  {
    id: "alerts",
    label: "告警中心",
    items: [{ label: "告警与通知", path: "/alerts", description: "管理告警规则、事件和飞书通知。" }],
  },
  {
    id: "mcp",
    label: "MCP 网关",
    items: [
      { label: "服务管理", path: "/mcp/servers", planned: true, description: "管理 MCP 服务接入和运行状态。" },
      { label: "工具管理", path: "/mcp/tools", planned: true, description: "管理工具发布、权限与调用范围。" },
      { label: "调用记录", path: "/mcp/logs", planned: true, description: "查询 MCP 工具调用和用量。" },
    ],
  },
  {
    id: "settings",
    label: "系统设置",
    items: [{ label: "平台设置", path: "/settings", description: "配置平台全局规则和日志归档策略。" }],
  },
];
