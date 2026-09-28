<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppSelect from "@/AppSelect.vue";
import { allDimensions, dimensionNames, type AnalyticsQuery, type Dimension } from "@/types/analytics";
import { showToast } from "@/utils/toast";

const props = defineProps<{
  modelValue: AnalyticsQuery;
  dimensions: Dimension[];
  loading?: boolean;
}>();
const emit = defineEmits<{ apply: [query: AnalyticsQuery] }>();
const draft = ref<AnalyticsQuery>({ ...props.modelValue });
watch(() => props.modelValue, (value) => { draft.value = { ...value }; });

const dimensionOptions = computed(() => props.dimensions.map((value) => ({
  value, label: dimensionNames[value],
})));
const scopeOptions = [
  { label: "全部维度", value: "" },
  ...allDimensions.map((value) => ({ value, label: dimensionNames[value] })),
];
const scopeHint = computed(() => draft.value.scope
  ? (["organization", "project", "key", "access_model", "provider"].includes(draft.value.scope)
    ? `输入${dimensionNames[draft.value.scope]} ID；未归属输入 none`
    : `输入完整${dimensionNames[draft.value.scope]}名称`)
  : "选择维度后输入筛选值");

function apply() {
  const start = Date.parse(`${draft.value.start_date}T00:00:00Z`);
  const end = Date.parse(`${draft.value.end_date}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start > end
    || (end - start) / 86400000 >= 90) {
    showToast("error", "日期范围须为 1 至 90 天");
    return;
  }
  if (draft.value.scope && !draft.value.value.trim()) {
    showToast("error", "请输入筛选值");
    return;
  }
  emit("apply", {
    ...draft.value,
    scope: draft.value.scope,
    value: draft.value.scope ? draft.value.value.trim() : "",
  });
}

function preset(days: number) {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - days + 1);
  draft.value.start_date = start.toISOString().slice(0, 10);
  draft.value.end_date = end.toISOString().slice(0, 10);
  apply();
}

function reset() {
  draft.value.scope = "";
  draft.value.value = "";
  apply();
}
</script>

<template>
  <form class="page-card analytics-filters" @submit.prevent="apply">
    <div class="analytics-filters__row">
      <span class="analytics-filters__caption">统计区间 · UTC</span>
      <button v-for="days in [7, 30, 90]" :key="days" class="app-control-button"
        type="button" :disabled="loading" @click="preset(days)">近 {{ days }} 天</button>
      <label>从 <input v-model="draft.start_date" class="app-control-input" type="date" required /></label>
      <label>至 <input v-model="draft.end_date" class="app-control-input" type="date" required /></label>
      <label>排行维度
        <AppSelect v-model="draft.dimension" :options="dimensionOptions" aria-label="排行维度" />
      </label>
    </div>
    <div class="analytics-filters__row">
      <span class="analytics-filters__caption">维度筛选</span>
      <AppSelect v-model="draft.scope" :options="scopeOptions" aria-label="筛选维度" />
      <input v-model="draft.value" class="app-control-input analytics-filters__value"
        :disabled="!draft.scope" :placeholder="scopeHint" aria-label="筛选值" />
      <button class="app-control-button app-control-button--primary" type="submit" :disabled="loading">
        {{ loading ? "查询中..." : "应用筛选" }}
      </button>
      <button class="app-control-button" type="button" :disabled="loading" @click="reset">清除维度</button>
    </div>
  </form>
</template>

<style scoped>
.analytics-filters { display: flex; flex-direction: column; gap: 12px; }
.analytics-filters__row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.analytics-filters__row label { display: flex; align-items: center; gap: 7px; color: #526778; font-size: 12px; }
.analytics-filters__caption { width: 90px; color: #526778; font-size: 12px; font-weight: 700; }
.analytics-filters :deep(.app-select) { width: 160px; }
.analytics-filters input[type="date"] { width: 152px; }
.analytics-filters__value { width: min(310px, 100%); }
@media (max-width: 650px) {
  .analytics-filters__caption { width: 100%; }
  .analytics-filters__value { flex: 1; min-width: 180px; }
}
</style>
