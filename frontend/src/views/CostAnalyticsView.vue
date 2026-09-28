<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import AnalyticsFilters from "@/AnalyticsFilters.vue";
import AnalyticsTrend from "@/AnalyticsTrend.vue";
import AppSelect from "@/AppSelect.vue";
import { fetchCost, fetchCurrencies } from "@/api/analytics";
import {
  dimensionNames, initialQuery, type AnalyticsQuery, type CostAnalytics, type Dimension,
} from "@/types/analytics";
import { analyticsLogFilters } from "@/utils/analyticsLogs";
import { showToast } from "@/utils/toast";

const router = useRouter();
const dimensions: Dimension[] = ["provider", "access_model", "project", "organization"];
const query = ref(initialQuery("provider"));
const currency = ref("CNY");
const currencies = ref(["CNY"]);
const data = ref<CostAnalytics | null>(null);
const loading = ref(false);
let sequence = 0;
const points = computed(() => data.value?.daily.map((item) => ({
  date: item.date, value: Number(item.estimated_cost),
})) ?? []);
const format = (value: number, digits = 2) => new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: digits,
}).format(value);
const total = computed(() => Number(data.value?.summary.estimated_cost ?? 0));
const share = (value: string) => total.value ? Number(value) / total.value * 100 : 0;
const colors = ["#238c79", "#50ad9a", "#88c9ad", "#a9d8cb", "#cbe8db"];
const slices = computed(() => {
  let offset = 0;
  const stops = (data.value?.ranking.slice(0, 5) ?? []).map((item, index) => {
    const next = offset + share(item.estimated_cost);
    const slice = `${colors[index]} ${offset}% ${next}%`;
    offset = next;
    return slice;
  });
  stops.push(`#eaf0ef ${offset}% 100%`);
  return `conic-gradient(${stops.join(", ")})`;
});

async function load(next: AnalyticsQuery, money = currency.value) {
  const current = ++sequence;
  query.value = { ...next };
  currency.value = money;
  data.value = null;
  loading.value = true;
  try {
    const result = await fetchCost(next, money);
    if (current === sequence) data.value = result;
  } catch {
    if (current === sequence) showToast("error", "成本分析加载失败");
  } finally {
    if (current === sequence) loading.value = false;
  }
}

function filterRanking(value: string) {
  void load({ ...query.value, scope: query.value.dimension, value });
}

onMounted(() => {
  void load(query.value);
  void fetchCurrencies().then((items) => { currencies.value = items; }).catch(() => {
    showToast("error", "获取可用币种失败");
  });
});
onUnmounted(() => { sequence++; data.value = null; });
</script>

<template>
  <section class="page-stack">
    <div class="page-heading">
      <p class="page-card__description">费用为网关按模型定价计算的估算值，不等同于供应商账单；不同币种不合计。</p>
      <button class="page-action" type="button" :disabled="loading" @click="load(query)">刷新数据</button>
    </div>
    <AnalyticsFilters :model-value="query" :dimensions="dimensions" :loading="loading" @apply="load" />
    <div class="page-card analytics-currency">
      <label>币种
        <AppSelect :model-value="currency" :options="currencies.map((item) => ({ label: item, value: item }))"
          aria-label="币种" :disabled="loading"
          @update:model-value="load(query, String($event))" />
      </label>
      <span>无定价或没有费用记录的请求单独统计；缺少上游 usage 时可能按预留量估算。</span>
    </div>
    <div v-if="loading" class="page-card analytics-empty" role="status">正在加载成本数据...</div>
    <template v-if="data">
      <div class="analytics-cards">
        <article class="page-card analytics-card"><span>估算总费用</span><strong>{{ format(total, 6) }} {{ data.currency }}</strong><small>仅含有该币种费用的请求</small></article>
        <article class="page-card analytics-card"><span>已计价请求</span><strong>{{ format(data.summary.priced_requests, 0) }}</strong><small>包括明确计价为 0 的请求</small></article>
        <article class="page-card analytics-card"><span>未计价请求</span><strong>{{ format(data.summary.unpriced_requests, 0) }}</strong><small>其他币种也计入此处</small></article>
        <article class="page-card analytics-card"><span>平均每次费用</span><strong>{{ data.summary.average_cost === null ? "-" : format(Number(data.summary.average_cost), 6) }}</strong><small>{{ data.currency }} / 已计价请求</small></article>
      </div>
      <div class="analytics-columns">
        <section class="page-card analytics-panel">
          <h2>费用趋势</h2><p>按 UTC 请求日期统计；今天的费用仍会变化。</p>
          <AnalyticsTrend :points="points" title="估算费用" :unit="` ${data.currency}`" :digits="4" />
        </section>
        <section class="page-card analytics-panel">
          <h2>{{ dimensionNames[data.dimension] }}费用占比</h2>
          <p>按估算费用排序，点击名称筛选；低于前十的维度未单独列出。</p>
          <div v-if="total > 0" class="analytics-donut" :style="{ background: slices }"
            role="img" :aria-label="`${dimensionNames[data.dimension]}前五名及其他的费用占比`">
            <div class="analytics-donut__hole"><strong>{{ format(total, 6) }}</strong><small>{{ data.currency }} 总估算费用</small></div>
          </div>
          <div v-for="(item, index) in data.ranking" :key="item.value" class="analytics-share">
            <button type="button" @click="filterRanking(item.value)">{{ item.label }}</button>
            <div class="analytics-share__track" :title="`${format(share(item.estimated_cost))}%`">
              <div class="analytics-share__fill"
                :style="{ width: `${share(item.estimated_cost)}%`, background: colors[index] ?? '#eaf0ef' }"></div>
            </div>
            <span>{{ format(share(item.estimated_cost), 1) }}%</span>
          </div>
          <p v-if="!data.ranking.length" class="analytics-empty">该范围暂无已计价请求</p>
        </section>
      </div>
      <section class="page-card analytics-panel">
        <h2>费用排行</h2><p>此表仅比较当前币种下有费用记录的请求。</p>
        <button class="app-control-button" type="button" @click="router.push({ path: '/logs', query: {
          filters: analyticsLogFilters(query, [
            { field: 'currency', operator: 'eq', value: currency },
            { field: 'estimated_cost', operator: 'gte', value: '0' },
          ]),
        } })">查看对应已计价调用日志</button>
        <div class="analytics-table-wrap">
          <table class="analytics-table">
            <thead><tr><th>名称</th><th>已计价请求</th><th>估算费用 ({{ data.currency }})</th><th>占比</th></tr></thead>
            <tbody>
              <tr v-for="item in data.ranking" :key="item.value">
                <td><button type="button" @click="filterRanking(item.value)">{{ item.label }}</button></td>
                <td>{{ format(item.priced_requests, 0) }}</td>
                <td>{{ format(Number(item.estimated_cost), 6) }}</td>
                <td>{{ format(share(item.estimated_cost), 1) }}%</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!data.ranking.length" class="analytics-empty">暂无费用数据</p>
        </div>
      </section>
    </template>
  </section>
</template>

<style src="@/styles/analytics.css"></style>
<style scoped>
.analytics-currency { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; }
.analytics-currency label { display: flex; align-items: center; gap: 8px; font-size: 12px; }
.analytics-currency span { color: #81909b; font-size: 12px; }
.analytics-share button { width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; background: none; border: 0; color: #217c70; cursor: pointer; }
.analytics-share span { width: 50px; text-align: right; }
.analytics-donut { display: grid; place-items: center; width: 180px; height: 180px; border-radius: 50%; margin: 4px auto 14px; }
.analytics-donut__hole { display: flex; flex-direction: column; justify-content: center; align-items: center; gap: 4px; width: 120px; height: 120px; border-radius: 50%; background: #fff; text-align: center; }
.analytics-donut__hole strong { max-width: 110px; overflow-wrap: anywhere; color: #264c4b; font-size: 16px; }
.analytics-donut__hole small { color: #81909b; font-size: 10px; }
</style>
