<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import AnalyticsFilters from "@/AnalyticsFilters.vue";
import AnalyticsTrend from "@/AnalyticsTrend.vue";
import { fetchPerformance } from "@/api/analytics";
import {
  dimensionNames, initialQuery, type AnalyticsQuery, type Dimension, type PerformanceAnalytics,
} from "@/types/analytics";
import { analyticsLogFilters } from "@/utils/analyticsLogs";
import { showToast } from "@/utils/toast";

const router = useRouter();
const dimensions: Dimension[] = ["access_model", "provider", "endpoint", "model_type"];
const query = ref(initialQuery("access_model"));
const data = ref<PerformanceAnalytics | null>(null);
const loading = ref(false);
const trend = ref<"avg_latency_ms" | "p95_latency_ms" | "p99_latency_ms"
  | "avg_ttft_ms" | "avg_tpot_ms" | "avg_tokens_per_second" | "success_rate">("avg_latency_ms");
let sequence = 0;
const points = computed(() => data.value?.daily.map((item) => ({
  date: item.date,
  value: trend.value === "success_rate"
    ? item.requests ? item.successes / item.requests * 100 : null
    : item[trend.value],
})) ?? []);
const format = (value: number | null, unit = " ms") =>
  value === null ? "-" : `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value)}${unit}`;
const rate = (ok: number, count: number) => count ? `${(100 * ok / count).toFixed(1)}%` : "-";

async function load(next: AnalyticsQuery) {
  const current = ++sequence;
  query.value = { ...next };
  data.value = null;
  loading.value = true;
  try {
    const result = await fetchPerformance(next);
    if (current === sequence) data.value = result;
  } catch {
    if (current === sequence) showToast("error", "性能分析加载失败");
  } finally {
    if (current === sequence) loading.value = false;
  }
}

function filterRanking(value: string) {
  void load({ ...query.value, scope: query.value.dimension, value });
}

onMounted(() => void load(query.value));
onUnmounted(() => { sequence++; data.value = null; });
</script>

<template>
  <section class="page-stack">
    <div class="page-heading">
      <p class="page-card__description">观察响应延迟、错误率及流式输出性能；统计日期按 UTC 请求时间计算。</p>
      <button class="page-action" type="button" :disabled="loading" @click="load(query)">刷新数据</button>
    </div>
    <AnalyticsFilters :model-value="query" :dimensions="dimensions" :loading="loading" @apply="load" />
    <div v-if="loading" class="page-card analytics-empty" role="status">正在加载性能数据...</div>
    <template v-if="data">
      <div class="analytics-cards">
        <article class="page-card analytics-card">
          <span>平均响应耗时</span><strong>{{ format(data.summary.avg_latency_ms) }}</strong>
          <small>{{ data.summary.latency_samples }} 个有效样本</small>
        </article>
        <article class="page-card analytics-card">
          <span>P95 响应耗时</span><strong>{{ format(data.summary.p95_latency_ms) }}</strong>
          <small>P99：{{ format(data.summary.p99_latency_ms) }}</small>
        </article>
        <article class="page-card analytics-card">
          <span>成功率</span><strong>{{ rate(data.summary.successes, data.summary.requests) }}</strong>
          <small>{{ data.summary.requests - data.summary.successes }} 次非 2xx / {{ data.summary.requests }} 次请求</small>
        </article>
        <article class="page-card analytics-card">
          <span>流式平均 TTFT</span><strong>{{ format(data.summary.avg_ttft_ms) }}</strong>
          <small>{{ data.summary.ttft_samples }} 个有效样本</small>
        </article>
        <article class="page-card analytics-card">
          <span>流式平均 TPOT</span><strong>{{ format(data.summary.avg_tpot_ms, " ms/token") }}</strong>
          <small>{{ data.summary.tpot_samples }} 个有效样本</small>
        </article>
        <article class="page-card analytics-card">
          <span>平均输出速度</span><strong>{{ format(data.summary.avg_tokens_per_second, " token/s") }}</strong>
          <small>{{ data.summary.speed_samples }} 个有效样本</small>
        </article>
      </div>
      <div class="analytics-columns">
        <section class="page-card analytics-panel">
          <h2>性能趋势</h2>
          <p>缺失性能指标的日期不会按 0 参与平均；首 Token 和输出指标仅适用于流式请求。</p>
          <div class="analytics-switch">
            <button v-for="item in ([
              ['avg_latency_ms', '平均耗时'], ['p95_latency_ms', 'P95'],
              ['p99_latency_ms', 'P99'], ['success_rate', '成功率'],
              ['avg_ttft_ms', 'TTFT'], ['avg_tpot_ms', 'TPOT'],
              ['avg_tokens_per_second', '输出速度'],
            ] as const)" :key="item[0]" type="button"
              :class="{ active: trend === item[0] }" @click="trend = item[0]">{{ item[1] }}</button>
          </div>
          <AnalyticsTrend :points="points" :title="trend"
            :unit="trend === 'success_rate' ? '%' : trend === 'avg_tokens_per_second' ? ' token/s' : ' ms'" />
        </section>
        <section class="page-card analytics-panel">
          <h2>错误分布</h2><p>按错误码及状态码归并，展示出现次数最多的 10 类。</p>
          <div class="analytics-table-wrap">
            <table class="analytics-table">
              <thead><tr><th>错误码</th><th>HTTP 状态</th><th>次数</th></tr></thead>
              <tbody><tr v-for="item in data.errors" :key="`${item.code}-${item.http_status}`">
                <td>{{ item.code }}</td><td>{{ item.http_status }}</td><td>{{ item.requests }}</td>
              </tr></tbody>
            </table>
            <p v-if="!data.errors.length" class="analytics-empty">该范围暂无失败请求</p>
          </div>
        </section>
      </div>
      <section class="page-card analytics-panel">
        <h2>{{ dimensionNames[data.dimension] }}性能排行</h2>
        <p>按调用次数排序；P95/P99 在当前维度各自的有效样本中计算。点击名称筛选。</p>
        <button class="app-control-button" type="button" @click="router.push({
          path: '/logs', query: { filters: analyticsLogFilters(query) },
        })">查看对应调用日志</button>
        <div class="analytics-table-wrap">
          <table class="analytics-table">
            <thead><tr><th>名称</th><th>调用</th><th>成功率</th><th>平均耗时</th><th>P95</th><th>P99</th><th>TTFT</th><th>TPOT</th><th>输出速度</th></tr></thead>
            <tbody>
              <tr v-for="item in data.ranking" :key="item.value">
                <td><button type="button" @click="filterRanking(item.value)">{{ item.label }}</button></td>
                <td>{{ item.requests }}</td><td>{{ rate(item.successes, item.requests) }}</td>
                <td :title="`${item.latency_samples} 个样本`">{{ format(item.avg_latency_ms) }}</td>
                <td>{{ format(item.p95_latency_ms) }}</td><td>{{ format(item.p99_latency_ms) }}</td>
                <td :title="`${item.ttft_samples} 个样本`">{{ format(item.avg_ttft_ms) }}</td>
                <td :title="`${item.tpot_samples} 个样本`">{{ format(item.avg_tpot_ms) }}</td>
                <td :title="`${item.speed_samples} 个样本`">{{ format(item.avg_tokens_per_second, " token/s") }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="!data.ranking.length" class="analytics-empty">该范围暂无调用</p>
        </div>
      </section>
      <p class="analytics-intro">
        TTFT 为从网关开始转发到首个内容片段的耗时；TPOT 为首个内容片段之后平均每输出 Token 的耗时。
        输出速度按有输出 Token 且总耗时大于 TTFT 的流式请求计算；不代表上游独立计时。
      </p>
    </template>
  </section>
</template>

<style src="@/styles/analytics.css"></style>
