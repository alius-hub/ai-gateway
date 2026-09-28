<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import AnalyticsFilters from "@/AnalyticsFilters.vue";
import AnalyticsTrend from "@/AnalyticsTrend.vue";
import { fetchUsage } from "@/api/analytics";
import {
  dimensionNames, initialQuery, type AnalyticsQuery, type Dimension, type UsageAnalytics,
} from "@/types/analytics";
import { analyticsLogFilters } from "@/utils/analyticsLogs";
import { showToast } from "@/utils/toast";

const router = useRouter();
const dimensions: Dimension[] = ["public_model", "access_model", "organization", "project", "key"];
const query = ref(initialQuery("public_model"));
const data = ref<UsageAnalytics | null>(null);
const loading = ref(false);
const trend = ref<"requests" | "total_tokens" | "input_tokens" | "output_tokens">("requests");
let sequence = 0;

const points = computed(() => data.value?.daily.map((item) => ({
  date: item.date, value: item[trend.value],
})) ?? []);
const format = (value: number) => new Intl.NumberFormat("zh-CN").format(value);
const rate = (ok: number, count: number) => count ? `${(100 * ok / count).toFixed(1)}%` : "-";

async function load(next: AnalyticsQuery) {
  const current = ++sequence;
  query.value = { ...next };
  data.value = null;
  loading.value = true;
  try {
    const result = await fetchUsage(next);
    if (current === sequence) data.value = result;
  } catch {
    if (current === sequence) showToast("error", "用量分析加载失败");
  } finally {
    if (current === sequence) loading.value = false;
  }
}

function filterRanking(value: string) {
  void load({ ...query.value, scope: query.value.dimension, value });
}

function openLogs() {
  void router.push({ path: "/logs", query: { filters: analyticsLogFilters(query.value) } });
}

onMounted(() => void load(query.value));
onUnmounted(() => { sequence++; data.value = null; });
</script>

<template>
  <section class="page-stack">
    <div class="page-heading">
      <p class="page-card__description">按请求发生时间分析调用量与 Token 消耗，日期按 UTC 统计。</p>
      <button class="page-action" type="button" :disabled="loading" @click="load(query)">刷新数据</button>
    </div>
    <AnalyticsFilters :model-value="query" :dimensions="dimensions" :loading="loading" @apply="load" />
    <div v-if="loading" class="page-card analytics-empty" role="status">正在加载用量数据...</div>
    <template v-if="data">
      <div class="analytics-cards">
        <article class="page-card analytics-card"><span>请求总数</span><strong>{{ format(data.summary.requests) }}</strong><small>包含无 Token 记录的请求</small></article>
        <article class="page-card analytics-card"><span>成功率</span><strong>{{ rate(data.summary.successes, data.summary.requests) }}</strong><small>{{ format(data.summary.successes) }} 次 HTTP 2xx</small></article>
        <article class="page-card analytics-card"><span>输入 Token</span><strong>{{ format(data.summary.input_tokens) }}</strong><small>缺失明细不计入</small></article>
        <article class="page-card analytics-card"><span>输出 Token</span><strong>{{ format(data.summary.output_tokens) }}</strong><small>总 Token：{{ format(data.summary.total_tokens) }}</small></article>
      </div>
      <div class="analytics-columns">
        <section class="page-card analytics-panel">
          <h2>用量趋势</h2><p>今天的数据仍在更新；切换指标查看同一时间段。</p>
          <div class="analytics-switch">
            <button v-for="item in ([
              ['requests', '请求数'], ['total_tokens', '总 Token'],
              ['input_tokens', '输入 Token'], ['output_tokens', '输出 Token'],
            ] as const)" :key="item[0]" type="button" :class="{ active: trend === item[0] }"
              @click="trend = item[0]">{{ item[1] }}</button>
          </div>
          <AnalyticsTrend :points="points" :title="trend" />
        </section>
        <section class="page-card analytics-panel">
          <h2>{{ dimensionNames[data.dimension] }}排行</h2>
          <p>按请求数排序，点击名称筛选该维度；最多显示 10 项。</p>
          <div class="analytics-table-wrap">
            <table class="analytics-table">
              <thead><tr><th>名称</th><th>请求</th><th>成功率</th><th>Token</th></tr></thead>
              <tbody>
                <tr v-for="item in data.ranking" :key="item.value">
                  <td><button type="button" @click="filterRanking(item.value)">{{ item.label }}</button></td>
                  <td>{{ format(item.requests) }}</td><td>{{ rate(item.successes, item.requests) }}</td>
                  <td>{{ format(item.total_tokens) }}</td>
                </tr>
              </tbody>
            </table>
            <p v-if="!data.ranking.length" class="analytics-empty">该范围暂无调用</p>
          </div>
          <button class="app-control-button" type="button" @click="openLogs">查看对应调用日志</button>
        </section>
      </div>
    </template>
  </section>
</template>

<style src="@/styles/analytics.css"></style>
