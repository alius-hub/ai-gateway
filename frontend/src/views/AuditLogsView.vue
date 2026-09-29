<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";

import AppFilterTags from "@/AppFilterTags.vue";
import AppListFilter from "@/AppListFilter.vue";
import AppPagination from "@/AppPagination.vue";
import AppSelect from "@/AppSelect.vue";
import { listAuditEvents, listAuditResources, type AuditEvent } from "@/api/logs";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
import { showToast } from "@/utils/toast";

type QuickQuery = {
  resource?: string; start_time?: string; end_time?: string;
};

const items = ref<AuditEvent[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const loading = ref(false);
const resource = ref("");
const resources = ref<string[]>([]);
const start = ref("");
const end = ref("");
const activeQuery = ref<QuickQuery>({});
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
let generation = 0;
let disposed = false;
const resourceOptions = computed(() => [
  { label: "全部资源", value: "" },
  ...resources.value.map((value) => ({ label: value, value })),
]);

async function loadResources() {
  try {
    const result = await listAuditResources();
    if (!disposed) resources.value = result;
  } catch {
    if (!disposed) showToast("error", "加载资源选项失败");
  }
}

async function load() {
  const current = ++generation;
  loading.value = true;
  items.value = [];
  total.value = 0;
  try {
    const result = await listAuditEvents(page.value, pageSize.value, activeQuery.value, filters.value);
    if (current !== generation) return;
    items.value = result.items;
    total.value = result.total;
  } catch {
    if (current === generation) showToast("error", "加载审计日志失败");
  } finally {
    if (current === generation) loading.value = false;
  }
}

function search() {
  if (start.value && end.value && start.value > end.value) {
    showToast("error", "开始时间不能晚于结束时间");
    return;
  }
  activeQuery.value = {
    resource: resource.value.trim() || undefined,
    start_time: start.value ? new Date(start.value).toISOString() : undefined,
    end_time: end.value ? new Date(end.value).toISOString() : undefined,
  };
  page.value = 1;
  void load();
}

function applyFilters(value: FilterGroup) {
  filters.value = value;
  page.value = 1;
  void load();
}

function changePageSize(value: number) {
  pageSize.value = value;
  page.value = 1;
  void load();
}

function refresh() {
  void loadResources();
  void load();
}

onUnmounted(() => { disposed = true; generation++; items.value = []; });
void loadResources();
void load();
</script>

<template>
  <section class="page-stack audit-logs">
    <div class="page-card audit-header">
      <div class="audit-heading">
        <h2>审计日志</h2>
        <p>查看登录及平台管理操作。记录操作人、时间、资源、路径和结果。</p>
      </div>
      <AppFilterTags :fields="listFilterFields['audit-events']" :model-value="filters" @apply="applyFilters" />
      <div class="app-list-toolbar-actions">
        <form class="audit-filters" @submit.prevent="search">
          <AppSelect v-model="resource" class="audit-resource" :options="resourceOptions"
                     placeholder="全部资源" aria-label="资源" />
          <label>开始时间 <input v-model="start" class="app-control-input" type="datetime-local" /></label>
          <label>结束时间 <input v-model="end" class="app-control-input" type="datetime-local" /></label>
          <button class="app-control-button" type="submit">查询</button>
          <button class="app-control-button" type="button" @click="refresh">刷新</button>
        </form>
        <AppListFilter :fields="listFilterFields['audit-events']" :model-value="filters" hide-tags @apply="applyFilters" />
      </div>
    </div>
    <div class="page-card audit-table-card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>资源</th><th>请求</th><th>来源 IP</th><th>结果</th></tr></thead>
          <tbody>
            <tr v-for="item in items" :key="item.id">
              <td>{{ new Date(item.created_at).toLocaleString() }}</td>
              <td>{{ item.actor_username }} (#{{ item.actor_user_id }})</td>
              <td>{{ { login: '登录', create: '创建', update: '更新', delete: '删除', rotate: '轮换 Key', reset_password: '重置密码' }[item.action as 'login' | 'create' | 'update' | 'delete' | 'rotate' | 'reset_password'] || item.action }}</td>
              <td>{{ item.resource }}</td>
              <td class="path">{{ item.method }} {{ item.path }}</td>
              <td>{{ item.ip_address || '-' }}</td>
              <td>{{ item.status_code }}</td>
            </tr>
            <tr v-if="!items.length"><td colspan="7" class="empty">{{ loading ? '正在加载...' : '暂无匹配的审计日志' }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination v-if="total > 0" v-model="page" :page-size="pageSize" :total="total"
                     :disabled="loading" @change="load" @update:page-size="changePageSize" />
    </div>
  </section>
</template>

<style scoped>
.audit-header{display:flex;align-items:center;flex-wrap:wrap;gap:12px}
.audit-heading{min-width:220px}
h2{margin:0 0 8px;font-size:20px}p{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.audit-filters{display:flex;align-items:center;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.audit-resource{width:150px;flex:0 0 150px}
.audit-filters label{display:flex;align-items:center;gap:6px;font-size:12px;color:#64748b;white-space:nowrap}
.audit-filters .app-control-input{width:150px;min-width:0}
.audit-filters label .app-control-input{width:172px}
.audit-table-card{padding:0;overflow:hidden}
.table-wrap{overflow-x:auto}
table{width:100%;min-width:900px;border-collapse:collapse;text-align:left}
th,td{padding:13px 16px;border-bottom:1px solid #edf1f3;font-size:12px;white-space:nowrap}
th{background:#f7f9fa;color:#6d8090}.path{font-family:monospace}.empty{text-align:center;padding:36px}
</style>
