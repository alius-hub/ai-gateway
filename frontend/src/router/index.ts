import type { RouteRecordRaw } from "vue-router";
import { createRouter, createWebHistory } from "vue-router";

import AdminLayout from "@/layouts/AdminLayout.vue";
import { getAccessToken } from "@/utils/auth";
import DashboardView from "@/views/DashboardView.vue";
import LoginView from "@/views/LoginView.vue";
import IdentityView from "@/views/IdentityView.vue";
import ModelCatalogView from "@/views/ModelCatalogView.vue";
import RoutingStrategiesView from "@/views/RoutingStrategiesView.vue";
import AggregateModelView from "@/views/AggregateModelView.vue";
import ProviderView from "@/views/ProviderView.vue";
import PlaygroundView from "@/views/PlaygroundView.vue";
import CredentialView from "@/views/CredentialView.vue";
import CallLogsView from "@/views/CallLogsView.vue";
import AuditLogsView from "@/views/AuditLogsView.vue";
import CostAnalyticsView from "@/views/CostAnalyticsView.vue";
import PerformanceAnalyticsView from "@/views/PerformanceAnalyticsView.vue";
import UsageAnalyticsView from "@/views/UsageAnalyticsView.vue";
import PlatformSettingsView from "@/views/PlatformSettingsView.vue";
import AlertsView from "@/views/AlertsView.vue";

import { navigation } from "./navigation";

const placeholder = () => import("@/views/PagePlaceholder.vue");
const plannedRoutes: RouteRecordRaw[] = navigation.flatMap((group) =>
  group.items
    .filter((item) => item.planned)
    .map((item) => ({
      path: item.path,
      component: placeholder,
      meta: {
        title: item.label,
        section: group.label,
        description: item.description,
        planned: true,
      },
    })),
);

const routes: RouteRecordRaw[] = [
  {
    path: "/login",
    component: LoginView,
    meta: { hidden: true, public: true },
  },
  {
    path: "/",
    component: AdminLayout,
    children: [
      {
        path: "",
        redirect: "/dashboard",
        meta: { hidden: true },
      },
      {
        path: "/dashboard",
        component: DashboardView,
        meta: {
          title: "总览",
          section: "工作台",
          description: "承接平台总请求量、Token 消耗、关键告警和趋势卡片。",
        },
      },
      {
        path: "/users",
        component: IdentityView,
        meta: { title: "用户管理", section: "用户与权限" },
      },
      {
        path: "/user-groups",
        component: IdentityView,
        meta: { title: "用户组", section: "用户与权限" },
      },
      {
        path: "/organizations",
        component: IdentityView,
        meta: {
          title: "组织管理",
          section: "用户与权限",
          description: "管理组织信息、成员、角色和租户边界。",
        },
      },
      {
        path: "/projects",
        component: IdentityView,
        meta: {
          title: "项目管理",
          section: "用户与权限",
          description: "管理项目、环境、成员、模型范围和访问边界。",
        },
      },
      {
        path: "/credentials",
        component: CredentialView,
        meta: {
          title: "项目 Key",
          section: "凭证中心",
          description: "管理项目凭证、模型授权和用量配置。",
        },
      },
      {
        path: "/credentials/personal",
        component: CredentialView,
        meta: { title: "个人 Key", section: "凭证中心", description: "管理个人凭证与模型授权。" },
      },
      {
        path: "/providers",
        component: ProviderView,
        meta: {
          title: "供应商管理",
          section: "模型治理",
          description: "管理接入源配置、认证方式、健康状态和基础地址。",
        },
      },
      {
        path: "/models",
        component: ModelCatalogView,
        meta: {
          title: "模型管理",
          section: "模型治理",
          description: "管理不同供应商的接入模型和上游连接。",
        },
      },
      {
        path: "/nodes",
        redirect: "/models",
        meta: { hidden: true },
      },
      {
        path: "/routing",
        component: RoutingStrategiesView,
        meta: { title: "路由策略", section: "模型治理", description: "查看平台内置的固定路由策略。" },
      },
      {
        path: "/models/aggregated",
        component: AggregateModelView,
        meta: { title: "聚合模型", section: "模型治理", description: "为对外模型选择路由策略和候选接入模型。" },
      },
      {
        path: "/playground",
        component: PlaygroundView,
        meta: { title: "在线调试", section: "模型治理", description: "调试模型对话及生成参数。" },
      },
      {
        path: "/logs",
        component: CallLogsView,
        meta: { title: "调用日志", section: "日志中心", description: "查询请求、用量和原始归档。" },
      },
      {
        path: "/logs/audit",
        component: AuditLogsView,
        meta: { title: "审计日志", section: "日志中心", description: "查询平台管理操作。" },
      },
      {
        path: "/analytics/usage",
        component: UsageAnalyticsView,
        meta: { title: "用量分析", section: "分析看板" },
      },
      {
        path: "/analytics/cost",
        component: CostAnalyticsView,
        meta: { title: "成本分析", section: "分析看板" },
      },
      {
        path: "/analytics/performance",
        component: PerformanceAnalyticsView,
        meta: { title: "性能分析", section: "分析看板" },
      },
      {
        path: "/settings",
        component: PlatformSettingsView,
        meta: { title: "平台设置", section: "系统设置", description: "配置日志图片归档策略。" },
      },
      {
        path: "/alerts",
        component: AlertsView,
        meta: { title: "告警与通知", section: "告警中心" },
      },
      ...plannedRoutes,
    ],
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach((to) => {
  const hasToken = Boolean(getAccessToken());
  const isPublicRoute = Boolean(to.meta.public);

  if (!isPublicRoute && !hasToken) {
    return {
      path: "/login",
      query: {
        redirect: to.fullPath,
      },
    };
  }

  if (to.path === "/login" && hasToken) {
    return "/dashboard";
  }

  return true;
});

export default router;
