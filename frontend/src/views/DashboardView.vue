<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { fetchOverviewSummary } from "@/api/overview";
import { locale, t } from "@/i18n";
import type { OverviewSummary } from "@/types/overview";
import { showToast } from "@/utils/toast";

const loading = ref(false);
const summary = ref<OverviewSummary | null>(null);

const metrics = computed(() => {
  if (!summary.value) {
    return [];
  }

  return [
    { label: t("总调用量"), value: formatInteger(summary.value.total_requests), hint: t("累计请求次数") },
    { label: t("总 Token"), value: formatInteger(summary.value.total_tokens), hint: t("累计消耗 Token") },
    { label: t("总成本"), value: formatCurrency(summary.value.total_cost), hint: t("累计预估成本") },
    { label: t("组织数"), value: formatInteger(summary.value.organization_count), hint: t("已创建组织") },
    { label: t("项目数"), value: formatInteger(summary.value.project_count), hint: t("已创建项目") },
    { label: t("凭证数"), value: formatInteger(summary.value.key_count), hint: t("可用 API Key 数量") },
    { label: t("模型数"), value: formatInteger(summary.value.model_count), hint: t("接入模型总数") },
  ];
});

const statusItems = computed(() => {
  if (!summary.value) {
    return [];
  }

  return [
    {
      label: t("数据库状态"),
      value: t(summary.value.database_status === "connected" ? "已连接" : "未就绪"),
      tone: summary.value.database_status === "connected" ? "success" : "warning",
    },
    {
      label: t("数据来源"),
      value: t(summary.value.data_source === "database" ? "实时数据库" : "启动占位数据"),
      tone: summary.value.data_source === "database" ? "success" : "warning",
    },
    {
      label: t("健康供应商"),
      value: `${formatInteger(summary.value.healthy_provider_count)} / ${formatInteger(summary.value.provider_count)}`,
      tone: "neutral",
    },
  ];
});

function formatInteger(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value);
}

function formatCurrency(value: string): string {
  const amount = Number.parseFloat(value);
  if (Number.isNaN(amount)) {
    return value;
  }

  return new Intl.NumberFormat(locale.value, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

async function loadSummary() {
  loading.value = true;

  try {
    summary.value = await fetchOverviewSummary();
  } catch (error) {
    showToast("error", t(error instanceof Error ? error.message : "总览数据加载失败"));
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadSummary();
});
</script>

<template>
  <section class="page-stack dashboard">
    <div class="page-heading">
      <p class="page-card__description">{{ t("查看平台调用量、资源规模与服务运行状态。") }}</p>
      <button class="page-action" type="button" :disabled="loading" @click="loadSummary">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7" />
        </svg>
        {{ t(loading ? "刷新中..." : "刷新数据") }}
      </button>
    </div>

    <div v-if="loading && !summary" class="page-card dashboard-loading" role="status">
      {{ t("正在加载平台数据...") }}
    </div>

    <div v-if="summary" class="dashboard-grid">
      <article v-for="(item, index) in metrics" :key="item.label" class="page-card dashboard-metric">
        <div class="dashboard-metric__top">
          <span class="dashboard-metric__label">{{ item.label }}</span>
          <span class="dashboard-metric__index">{{ String(index + 1).padStart(2, "0") }}</span>
        </div>
        <strong class="dashboard-metric__value" :title="item.value">{{ item.value }}</strong>
        <span class="dashboard-metric__hint">{{ item.hint }}</span>
      </article>
    </div>

    <div v-if="summary" class="dashboard-panels">
      <section class="page-card dashboard-panel">
        <div class="dashboard-panel__heading">
          <div>
            <h2 class="dashboard-panel__title">{{ t("服务状态") }}</h2>
            <p class="dashboard-panel__desc">{{ t(summary.status_message) }}</p>
          </div>
          <span class="dashboard-panel__tag">{{ t("实时概况") }}</span>
        </div>
        <div class="dashboard-status-list">
          <div v-for="item in statusItems" :key="item.label" class="dashboard-status-item">
            <span>{{ item.label }}</span>
            <strong :class="`dashboard-status-item--${item.tone}`">{{ item.value }}</strong>
          </div>
        </div>
      </section>

      <section class="page-card dashboard-panel">
        <div class="dashboard-panel__heading">
          <div>
            <h2 class="dashboard-panel__title">{{ t("统计说明") }}</h2>
            <p class="dashboard-panel__desc">{{ t("当前展示平台累计指标及基础资源数量。") }}</p>
          </div>
          <span class="dashboard-panel__tag">{{ t("数据快照") }}</span>
        </div>
        <div class="dashboard-detail">
          <span>{{ t("统计时间") }}</span>
          <strong>{{ new Date(summary.generated_at).toLocaleString(locale) }}</strong>
        </div>
        <div class="dashboard-detail">
          <span>{{ t("数据来源") }}</span>
          <strong>{{ t(summary.data_source === "database" ? "实时数据库" : "启动占位数据") }}</strong>
        </div>
        <div class="dashboard-detail">
          <span>{{ t("成本口径") }}</span>
          <strong>{{ t("预估费用 · USD") }}</strong>
        </div>
        <p class="dashboard-panel__foot">{{ t("更多趋势及明细将在分析看板中展示。") }}</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.dashboard-loading {
  color: #708192;
  font-size: 13px;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.dashboard-metric {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 142px;
  padding: 20px;
}

.dashboard-metric__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dashboard-metric__label {
  color: #6e8090;
  font-size: 12px;
  font-weight: 600;
}

.dashboard-metric__index {
  color: #b4c9c5;
  font-size: 11px;
  font-weight: 700;
}

.dashboard-metric__value {
  overflow: hidden;
  color: #1c3441;
  font-size: clamp(22px, 2vw, 30px);
  letter-spacing: -0.04em;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-metric__hint {
  margin-top: auto;
  color: #91a0ad;
  font-size: 11px;
}

.dashboard-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.dashboard-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-height: 80px;
}

.dashboard-panel__title {
  margin: 0 0 8px;
  color: #1b2d3e;
  font-size: 16px;
}

.dashboard-panel__desc {
  margin: 0;
  color: #8493a0;
  font-size: 12px;
  line-height: 1.6;
}

.dashboard-panel__tag {
  flex: none;
  padding: 5px 8px;
  border-radius: 6px;
  background: #f0f7f5;
  color: #428a7d;
  font-size: 10px;
}

.dashboard-status-list {
  display: flex;
  flex-direction: column;
}

.dashboard-status-item,
.dashboard-detail {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 47px;
  border-top: 1px solid #edf1f3;
  color: #788998;
  font-size: 12px;
}

.dashboard-status-item strong,
.dashboard-detail strong {
  color: #263b4b;
  font-size: 12px;
  font-weight: 650;
  text-align: right;
}

.dashboard-status-item strong.dashboard-status-item--success {
  color: #19816d;
}

.dashboard-status-item strong.dashboard-status-item--warning {
  color: #ae7740;
}

.dashboard-panel__foot {
  margin: 16px 0 0;
  color: #9aa7b3;
  font-size: 11px;
}

@media (max-width: 1200px) {
  .dashboard-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .dashboard-panels {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 520px) {
  .dashboard-grid {
    gap: 10px;
  }

  .dashboard-metric {
    min-height: 125px;
    padding: 16px;
  }

  .dashboard-metric__value {
    font-size: 22px;
  }
}
</style>
