<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { fetchOverviewActivity, fetchOverviewSummary } from "@/api/overview";
import { locale, t } from "@/i18n";
import type { OverviewActivity, OverviewSummary } from "@/types/overview";
import { showToast } from "@/utils/toast";

const loading = ref(false);
const summary = ref<OverviewSummary | null>(null);
const activity = ref<OverviewActivity | null>(null);
const days = ref<7 | 30>(7);
const chartMetric = ref<"requests" | "tokens">("requests");
let loadId = 0;

const maxChartValue = computed(() => Math.max(
  1, ...(activity.value?.daily.map((day) => day[chartMetric.value]) ?? []),
));
const successRate = computed(() => activity.value?.total_requests
  ? `${(activity.value.successful_requests / activity.value.total_requests * 100).toFixed(1)}%`
  : "—");

const metrics = computed(() => {
  if (!summary.value) {
    return [];
  }

  return [
    { label: t("总调用量"), value: formatInteger(summary.value.total_requests), hint: t("累计请求次数") },
    { label: t("总 Token"), value: formatInteger(summary.value.total_tokens), hint: t("累计消耗 Token") },
    { label: t("组织数"), value: formatInteger(summary.value.organization_count), hint: t("已创建组织") },
    { label: t("项目数"), value: formatInteger(summary.value.project_count), hint: t("已创建项目") },
    { label: t("凭证数"), value: formatInteger(summary.value.key_count), hint: t("API Key 总数") },
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

async function loadDashboard() {
  const currentLoad = ++loadId;
  loading.value = true;
  const [summaryResult, activityResult] = await Promise.allSettled([
    fetchOverviewSummary(), fetchOverviewActivity(days.value),
  ]);
  if (currentLoad !== loadId) return;
  if (summaryResult.status === "fulfilled") summary.value = summaryResult.value;
  else showToast("error", t("总览数据加载失败"));
  if (activityResult.status === "fulfilled") activity.value = activityResult.value;
  else {
    activity.value = null;
    showToast("error", t("运营数据加载失败"));
  }
  if (currentLoad === loadId) {
    loading.value = false;
  }
}

function changeDays(value: 7 | 30) {
  if (days.value === value) return;
  days.value = value;
  activity.value = null;
  void loadDashboard();
}

onMounted(() => {
  void loadDashboard();
});
</script>

<template>
  <section class="page-stack dashboard">
    <div class="page-heading">
      <p class="page-card__description">{{ t("查看平台调用量、资源规模与服务运行状态。") }}</p>
      <button class="page-action" type="button" :disabled="loading" @click="loadDashboard">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7" />
        </svg>
        {{ t(loading ? "刷新中..." : "刷新数据") }}
      </button>
    </div>

    <div v-if="loading && !summary && !activity" class="page-card dashboard-loading" role="status">
      {{ t("正在加载平台数据...") }}
    </div>

    <div v-if="activity" class="dashboard-grid dashboard-grid--activity">
      <article class="page-card dashboard-metric">
        <span class="dashboard-metric__label">{{ t("周期调用量") }}</span>
        <strong class="dashboard-metric__value">{{ formatInteger(activity.total_requests) }}</strong>
        <span class="dashboard-metric__hint">{{ t("近 {days} 天 · UTC", { days }) }}</span>
      </article>
      <article class="page-card dashboard-metric">
        <span class="dashboard-metric__label">{{ t("调用成功率") }}</span>
        <strong class="dashboard-metric__value">{{ successRate }}</strong>
        <span class="dashboard-metric__hint">{{ t("HTTP 2xx / 周期调用量") }}</span>
      </article>
      <article class="page-card dashboard-metric">
        <span class="dashboard-metric__label">{{ t("周期 Token") }}</span>
        <strong class="dashboard-metric__value">{{ formatInteger(activity.total_tokens) }}</strong>
        <span class="dashboard-metric__hint">{{ t("按调用发生时间统计") }}</span>
      </article>
    </div>

    <section class="page-card dashboard-panel dashboard-chart">
      <div class="dashboard-panel__heading">
        <div>
          <h2 class="dashboard-panel__title">{{ t("调用趋势") }}</h2>
          <p class="dashboard-panel__desc">{{ t("按 UTC 自然日统计，今天的数据持续更新。") }}</p>
        </div>
        <div class="dashboard-controls">
          <button v-for="value in ([7, 30] as const)" :key="value" type="button"
            :class="['dashboard-control', { 'is-active': days === value }]"
            :aria-pressed="days === value" @click="changeDays(value)">{{ t(value === 7 ? "近 7 天" : "近 30 天") }}</button>
        </div>
      </div>
      <div class="dashboard-controls dashboard-controls--metric">
        <button v-for="metric in (['requests', 'tokens'] as const)" :key="metric" type="button"
          :class="['dashboard-control', { 'is-active': chartMetric === metric }]"
          :aria-pressed="chartMetric === metric" @click="chartMetric = metric">{{ t(metric === "requests" ? "调用量" : "Token") }}</button>
      </div>
      <div v-if="loading && !activity" class="dashboard-empty" role="status">{{ t("正在加载平台数据...") }}</div>
      <div v-else-if="activity?.total_requests" class="dashboard-bars" role="img"
        :aria-label="t('近 {days} 天调用趋势', { days })">
        <div v-for="day in activity.daily" :key="day.date" class="dashboard-bar">
          <span class="dashboard-bar__value">{{ formatInteger(day[chartMetric]) }}</span>
          <div class="dashboard-bar__track" :title="`${day.date}: ${formatInteger(day[chartMetric])}`">
            <div class="dashboard-bar__fill" :style="{ height: `${day[chartMetric] / maxChartValue * 100}%` }"></div>
          </div>
          <span class="dashboard-bar__date">{{ day.date.slice(5) }}</span>
        </div>
      </div>
      <div v-else class="dashboard-empty">{{ t("该周期暂无调用数据") }}</div>
    </section>

    <div v-if="activity" class="dashboard-panels">
      <section class="page-card dashboard-panel">
        <div class="dashboard-panel__heading">
          <div><h2 class="dashboard-panel__title">{{ t("热门模型") }}</h2>
            <p class="dashboard-panel__desc">{{ t("按周期内调用次数排序") }}</p></div>
          <RouterLink class="dashboard-link" to="/models">{{ t("查看模型") }} →</RouterLink>
        </div>
        <div v-if="!activity.top_models.length" class="dashboard-empty">{{ t("该周期暂无调用数据") }}</div>
        <div v-for="(model, index) in activity.top_models" :key="model.name" class="dashboard-list-row">
          <span class="dashboard-list-row__name"><small>{{ index + 1 }}</small>{{ model.name }}</span>
          <strong>{{ formatInteger(model.requests) }}</strong>
        </div>
      </section>
      <section class="page-card dashboard-panel">
        <div class="dashboard-panel__heading">
          <div><h2 class="dashboard-panel__title">{{ t("最近失败调用") }}</h2>
            <p class="dashboard-panel__desc">{{ t("周期内非 2xx 响应，最多展示 5 条") }}</p></div>
          <RouterLink class="dashboard-link" to="/logs">{{ t("查看日志") }} →</RouterLink>
        </div>
        <div v-if="!activity.recent_failures.length" class="dashboard-empty">{{ t("该周期暂无失败调用") }}</div>
        <RouterLink v-for="failure in activity.recent_failures" :key="failure.request_id"
          class="dashboard-list-row dashboard-list-row--link" to="/logs">
          <span class="dashboard-list-row__name">{{ failure.model }} <small>{{ new Date(failure.created_at).toLocaleString(locale) }}</small></span>
          <strong class="dashboard-error">{{ failure.http_status }}</strong>
        </RouterLink>
      </section>
    </div>

    <h2 v-if="summary" class="dashboard-section-title">{{ t("平台资源") }}</h2>
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
        <p class="dashboard-panel__foot">{{ t("费用记录可能包含不同币种，暂不在此合并展示。") }}</p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.dashboard-grid--activity {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.dashboard-section-title {
  margin: 10px 0 0;
  color: #1b2d3e;
  font-size: 17px;
}

.dashboard-chart {
  min-width: 0;
}

.dashboard-controls {
  display: flex;
  gap: 4px;
  flex: none;
  padding: 3px;
  border-radius: 8px;
  background: #f2f6f7;
}

.dashboard-controls--metric {
  width: max-content;
  margin-bottom: 18px;
}

.dashboard-control {
  padding: 6px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #667a87;
  cursor: pointer;
  font: inherit;
  font-size: 12px;
}

.dashboard-control.is-active {
  background: #fff;
  color: #177d70;
  box-shadow: 0 1px 5px #152c381a;
}

.dashboard-control:focus-visible,
.dashboard-link:focus-visible,
.dashboard-list-row--link:focus-visible {
  outline: 2px solid #177d70;
  outline-offset: 2px;
}

.dashboard-bars {
  display: flex;
  align-items: stretch;
  gap: 6px;
  height: 226px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.dashboard-bar {
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 7px;
  min-width: 18px;
  color: #728493;
  font-size: 10px;
}

.dashboard-bar__value {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-bar__track {
  display: flex;
  align-items: flex-end;
  width: 100%;
  flex: 1;
  border-radius: 5px 5px 0 0;
  background: #f2f7f6;
}

.dashboard-bar__fill {
  width: 100%;
  min-height: 0;
  border-radius: 5px 5px 0 0;
  background: linear-gradient(#3db6a5, #198b7b);
}

.dashboard-bar__date {
  white-space: nowrap;
}

.dashboard-empty {
  display: grid;
  place-items: center;
  min-height: 98px;
  color: #91a0ad;
  font-size: 12px;
}

.dashboard-link {
  flex: none;
  color: #198b7b;
  font-size: 12px;
}

.dashboard-list-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 48px;
  border-top: 1px solid #edf1f3;
  color: #263b4b;
  font-size: 12px;
}

.dashboard-list-row__name {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dashboard-list-row__name small {
  flex: none;
  color: #91a0ad;
}

.dashboard-list-row--link:hover {
  color: #198b7b;
}

.dashboard-error {
  color: #b65650;
}

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
  .dashboard-grid--activity {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .dashboard-panels {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 520px) {
  .dashboard-grid--activity {
    grid-template-columns: minmax(0, 1fr);
  }

  .dashboard-chart .dashboard-panel__heading {
    flex-wrap: wrap;
  }

  .dashboard-bar {
    min-width: 26px;
  }

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
