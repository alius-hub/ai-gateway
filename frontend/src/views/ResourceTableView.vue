<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import {
  fetchAccessModels,
  fetchAggregateModels,
  fetchCredentials,
  fetchNodes,
  fetchOrganizations,
  fetchProjects,
  fetchProviders,
} from "@/api/resources";
import type { PageResult } from "@/types/list";

type RowRecord = Record<string, string | number | null | undefined>;

interface ResourceConfig {
  title: string;
  description: string;
  fetcher: () => Promise<PageResult<unknown>>;
  columns: Array<{ key: string; label: string }>;
}

const route = useRoute();
const loading = ref(false);
const errorMessage = ref("");
const rows = ref<RowRecord[]>([]);
const total = ref(0);

const configMap: Record<string, ResourceConfig> = {
  "/organizations": {
    title: "组织管理",
    description: "当前展示组织清单，后端优先读取数据库；数据库不可用时自动回落到演示数据。",
    fetcher: fetchOrganizations,
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "组织名称" },
      { key: "code", label: "组织编码" },
      { key: "status", label: "状态" },
      { key: "description", label: "描述" },
    ],
  },
  "/projects": {
    title: "项目管理",
    description: "承接项目环境、归属组织和项目级访问边界。",
    fetcher: fetchProjects,
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "项目名称" },
      { key: "code", label: "项目编码" },
      { key: "environment", label: "环境" },
      { key: "organization_id", label: "组织 ID" },
      { key: "status", label: "状态" },
    ],
  },
  "/credentials": {
    title: "凭证管理",
    description: "展示项目 Key 的基础清单，后续继续扩展轮换、过期和模型范围控制。",
    fetcher: fetchCredentials,
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "凭证名称" },
      { key: "key_prefix", label: "Key 前缀" },
      { key: "scope_type", label: "作用域" },
      { key: "project_id", label: "项目 ID" },
      { key: "status", label: "状态" },
    ],
  },
  "/providers": {
    title: "供应商管理",
    description: "展示接入供应商基础信息和健康状态。",
    fetcher: fetchProviders,
    columns: [
      { key: "id", label: "ID" },
      { key: "name", label: "供应商" },
      { key: "code", label: "编码" },
      { key: "provider_type", label: "类型" },
      { key: "health_status", label: "健康状态" },
      { key: "base_url", label: "基础地址" },
    ],
  },
  "/models": {
    title: "模型治理",
    description: "当前先同时展示接入模型和聚合模型，方便你确认数据是否联通。",
    fetcher: async () => {
      const [accessModels, aggregateModels] = await Promise.all([
        fetchAccessModels(),
        fetchAggregateModels(),
      ]);

      return {
        items: [
          ...accessModels.items.map((item) => ({
            kind: "接入模型",
            id: item.id,
            code: item.access_model_code,
            name: item.provider_model_name,
            model_type: item.model_type,
            strategy: "-",
            status: item.status,
          })),
          ...aggregateModels.items.map((item) => ({
            kind: "聚合模型",
            id: item.id,
            code: item.aggregate_model_code,
            name: item.public_model_name,
            model_type: item.model_type,
            strategy: item.default_routing_strategy,
            status: item.status,
          })),
        ],
        page: 1,
        page_size: accessModels.total + aggregateModels.total,
        total: accessModels.total + aggregateModels.total,
      };
    },
    columns: [
      { key: "kind", label: "类型" },
      { key: "id", label: "ID" },
      { key: "code", label: "模型编码" },
      { key: "name", label: "显示名称" },
      { key: "model_type", label: "模型类型" },
      { key: "strategy", label: "路由策略" },
      { key: "status", label: "状态" },
    ],
  },
  "/nodes": {
    title: "节点管理",
    description: "展示节点治理核心字段，后续可以继续扩展并发、RPM 和 TPM 配置。",
    fetcher: fetchNodes,
    columns: [
      { key: "id", label: "ID" },
      { key: "node_name", label: "节点名称" },
      { key: "node_code", label: "节点编码" },
      { key: "model_type", label: "模型类型" },
      { key: "health_status", label: "健康状态" },
      { key: "weight", label: "权重" },
      { key: "priority", label: "优先级" },
      { key: "region", label: "地域" },
    ],
  },
};

const currentConfig = computed(() => configMap[route.path]);

function formatValue(value: RowRecord[string]) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  return String(value);
}

async function loadData() {
  if (!currentConfig.value) {
    rows.value = [];
    total.value = 0;
    return;
  }

  loading.value = true;
  errorMessage.value = "";

  try {
    const response = await currentConfig.value.fetcher();
    rows.value = response.items as RowRecord[];
    total.value = response.total;
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "页面数据加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadData();
});
</script>

<template>
  <section class="resource-page" v-if="currentConfig">
    <div class="page-card">
      <div class="page-card__badge">{{ route.meta.section ?? "模块页面" }}</div>
      <h1 class="page-card__title">{{ currentConfig.title }}</h1>
      <p class="page-card__description">{{ currentConfig.description }}</p>
      <p class="resource-page__meta">当前记录数：{{ total }}{{ loading ? " / 加载中..." : "" }}</p>
    </div>

    <div v-if="errorMessage" class="resource-page__error">
      {{ errorMessage }}
    </div>

    <div class="page-card resource-table-card">
      <table class="resource-table">
        <thead>
          <tr>
            <th v-for="column in currentConfig.columns" :key="column.key">
              {{ column.label }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="`${route.path}-${index}`">
            <td v-for="column in currentConfig.columns" :key="column.key">
              {{ formatValue(row[column.key]) }}
            </td>
          </tr>
          <tr v-if="!rows.length && !loading">
            <td :colspan="currentConfig.columns.length" class="resource-table__empty">
              暂无数据
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.resource-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.resource-page__meta {
  margin: 16px 0 0;
  color: #64748b;
}

.resource-page__error {
  padding: 14px 16px;
  border-radius: 14px;
  background: #fee2e2;
  color: #b91c1c;
}

.resource-table-card {
  overflow: hidden;
  padding: 0;
}

.resource-table {
  width: 100%;
  border-collapse: collapse;
}

.resource-table th,
.resource-table td {
  padding: 14px 18px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  font-size: 14px;
}

.resource-table th {
  background: #f8fafc;
  color: #334155;
  font-weight: 700;
}

.resource-table__empty {
  padding: 36px 0;
  text-align: center;
  color: #64748b;
}
</style>
