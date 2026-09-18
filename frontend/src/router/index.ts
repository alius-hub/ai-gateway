import type { RouteRecordRaw } from "vue-router";
import { createRouter, createWebHistory } from "vue-router";

import AdminLayout from "@/layouts/AdminLayout.vue";
import { getAccessToken } from "@/utils/auth";
import DashboardView from "@/views/DashboardView.vue";
import LoginView from "@/views/LoginView.vue";
import ResourceTableView from "@/views/ResourceTableView.vue";
const placeholder = () => import("@/views/PagePlaceholder.vue");

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
        path: "/organizations",
        component: ResourceTableView,
        meta: {
          title: "组织管理",
          section: "用户与权限",
          description: "管理组织信息、成员、角色和租户边界。",
        },
      },
      {
        path: "/projects",
        component: ResourceTableView,
        meta: {
          title: "项目管理",
          section: "用户与权限",
          description: "管理项目、环境、成员、模型范围和访问边界。",
        },
      },
      {
        path: "/credentials",
        component: ResourceTableView,
        meta: {
          title: "凭证管理",
          section: "凭证中心",
          description: "统一承接个人 Key、项目 Key、轮换和状态控制。",
        },
      },
      {
        path: "/providers",
        component: ResourceTableView,
        meta: {
          title: "供应商管理",
          section: "模型管理",
          description: "管理接入源配置、认证方式、健康状态和基础地址。",
        },
      },
      {
        path: "/models",
        component: ResourceTableView,
        meta: {
          title: "模型治理",
          section: "模型管理",
          description: "管理接入模型、聚合模型、模型能力分类和发布策略。",
        },
      },
      {
        path: "/nodes",
        component: ResourceTableView,
        meta: {
          title: "节点管理",
          section: "模型管理",
          description: "管理节点权重、优先级、并发、Token 和健康检查配置。",
        },
      },
      {
        path: "/routing",
        component: placeholder,
        meta: {
          title: "路由策略",
          section: "模型管理",
          description: "管理项目级模型策略、调度规则、灰度和 fallback。",
        },
      },
      {
        path: "/logs",
        component: placeholder,
        meta: {
          title: "日志中心",
          section: "审计分析",
          description: "查询调用日志、审计日志和安全事件。",
        },
      },
      {
        path: "/settings",
        component: placeholder,
        meta: {
          title: "系统设置",
          section: "平台配置",
          description: "承接环境配置、全局规则、告警通道和系统级开关。",
        },
      },
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
