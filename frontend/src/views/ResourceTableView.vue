<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import {
  fetchAccessModels,
  fetchAggregateModels,
  fetchCredentials,
  fetchOrganizations,
  fetchProjects,
  fetchProviders,
} from "@/api/resources";
import { t } from "@/i18n";
import type { PageResult } from "@/types/list";
import { showToast } from "@/utils/toast";

type RowRecord = Record<string, string | number | null | undefined>;

interface ResourceConfig {
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
    description: "查看平台组织的基本信息与当前状态。",
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
    description: "查看项目所属组织、运行环境及启用状态。",
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
    description: "查看项目凭证的基本信息与使用范围。",
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
    description: "查看模型供应商的接入信息与健康状态。",
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
    description: "集中查看接入模型与对外聚合模型。",
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
};

const currentConfig = computed(() => configMap[route.path]);

function isStatusColumn(key: string) {
  return key === "status" || key === "health_status";
}

function statusLabel(key: string, value: RowRecord[string]) {
  if (key === "status") return value === 1 ? t("启用") : value === 0 ? t("停用") : formatValue(value);
  const labels: Record<string, string> = {
    healthy: "健康",
    unhealthy: "异常",
    unknown: "未知",
  };
  return labels[String(value)] ? t(labels[String(value)]) : formatValue(value);
}

function statusTone(value: RowRecord[string]) {
  if (value === 1 || value === "healthy") return "is-success";
  if (value === 0 || value === "unhealthy") return "is-muted";
  return "is-neutral";
}

function formatValue(value: RowRecord[string]) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }

  return String(value);
}

async function loadData() {
  const requestId = ++latestRequestId;
  if (!currentConfig.value) {
    rows.value = [];
    total.value = 0;
    return;
  }

  loading.value = true;
  errorMessage.value = "";

  try {
    const response = await currentConfig.value.fetcher();
    if (requestId !== latestRequestId) return;
    rows.value = response.items as RowRecord[];
    total.value = response.total;
  } catch (error) {
    if (requestId !== latestRequestId) return;
    errorMessage.value = error instanceof Error ? error.message : "页面数据加载失败";
    showToast("error", t(errorMessage.value));
  } finally {
    if (requestId === latestRequestId) loading.value = false;
  }
}

let latestRequestId = 0;
watch(
  () => route.path,
  () => {
    rows.value = [];
    total.value = 0;
    void loadData();
  },
  { immediate: true },
);
</script>

<template>
  <section v-if="currentConfig" class="page-stack resource-page">
    <div class="page-heading">
      <p class="page-card__description">{{ t(currentConfig.description) }}</p>
      <button class="page-action" type="button" :disabled="loading" @click="loadData">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7" />
        </svg>
        {{ t(loading ? "刷新中..." : "刷新列表") }}
      </button>
    </div>

    <div class="page-card resource-table-card">
      <div class="resource-table-card__heading">
        <div>
          <h2>{{ t("资源列表") }}</h2>
          <p>{{ t("当前共 {count} 条记录", { count: total }) }}</p>
        </div>
        <span class="resource-table-card__count">{{ total }}</span>
      </div>
      <div class="resource-table-scroll">
        <table class="resource-table">
          <thead>
            <tr>
              <th v-for="column in currentConfig.columns" :key="column.key" scope="col">
                {{ t(column.label) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, index) in rows" :key="`${route.path}-${row.kind ?? ''}-${row.id ?? index}`">
              <td v-for="column in currentConfig.columns" :key="column.key">
                <span
                  v-if="isStatusColumn(column.key)"
                  class="resource-status"
                  :class="statusTone(row[column.key])"
                >
                  <span class="resource-status__dot"></span>
                  {{ statusLabel(column.key, row[column.key]) }}
                </span>
                <span v-else :title="formatValue(row[column.key])">{{ column.key === "kind" ? t(formatValue(row[column.key])) : formatValue(row[column.key]) }}</span>
              </td>
            </tr>
            <tr v-if="!rows.length">
              <td :colspan="currentConfig.columns.length" class="resource-table__empty" role="status">
                {{ t(loading ? "正在加载数据..." : errorMessage ? "数据加载失败，请重试" : "暂无数据") }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </section>
</template>

<style scoped>
.resource-table-card {
  min-width: 0;
  overflow: hidden;
  padding: 0;
}

.resource-table-card__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 20px 24px;
}

.resource-table-card__heading h2 {
  margin: 0 0 6px;
  color: #263747;
  font-size: 15px;
}

.resource-table-card__heading p {
  margin: 0;
  color: #91a0ac;
  font-size: 12px;
}

.resource-table-card__count {
  display: grid;
  place-items: center;
  min-width: 32px;
  height: 27px;
  padding: 0 8px;
  border-radius: 7px;
  background: #edf7f3;
  color: #298272;
  font-size: 12px;
  font-weight: 650;
}

.resource-table-scroll {
  overflow-x: auto;
}

.resource-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
}

.resource-table th,
.resource-table td {
  padding: 14px 20px;
  border-top: 1px solid #edf1f3;
  text-align: left;
  font-size: 12px;
  white-space: nowrap;
}

.resource-table th {
  background: #f7f9fa;
  color: #6d8090;
  font-size: 11px;
  font-weight: 650;
}

.resource-table td {
  max-width: 260px;
  overflow: hidden;
  color: #344b59;
  text-overflow: ellipsis;
}

.resource-table tbody tr:hover {
  background: #f7fbf9;
}

.resource-table td.resource-table__empty {
  height: 136px;
  text-align: center;
  color: #91a0ac;
}

.resource-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 8px;
  border-radius: 6px;
  background: #f1f5f6;
  color: #687c8b;
}

.resource-status__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}

.resource-status.is-success {
  background: #e9f7f0;
  color: #208269;
}

.resource-status.is-muted {
  background: #f6f0ef;
  color: #aa685c;
}

@media (max-width: 560px) {
  .resource-table-card__heading {
    padding: 18px 20px;
  }
}
</style>
