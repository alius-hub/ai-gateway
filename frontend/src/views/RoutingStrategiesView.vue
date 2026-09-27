<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";

import { listBuiltinStrategies, type BuiltinStrategy } from "@/api/workflows";
import { showToast } from "@/utils/toast";

const strategies = ref<BuiltinStrategy[]>([]);
const loading = ref(true);

onMounted(async () => {
  try {
    strategies.value = (await listBuiltinStrategies()).items;
  } catch {
    showToast("error", "加载内置策略失败");
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <div class="page-stack">
    <div class="page-card">
      <div class="strategy-heading">
        <div><h2>内置路由策略</h2><p>策略由平台代码提供，无需创建或编排。新建聚合模型时选择策略并配置接入模型。</p></div>
        <RouterLink class="page-action" to="/models/aggregated">前往聚合模型</RouterLink>
      </div>
      <div v-if="loading" class="strategy-state">正在加载策略...</div>
      <div v-else-if="!strategies.length" class="strategy-state">暂无可用策略。</div>
      <div v-else class="strategy-grid">
        <article v-for="strategy in strategies" :key="strategy.code" class="strategy-card">
          <h3>{{ strategy.name }}</h3>
          <p>{{ strategy.description }}</p>
          <span>{{ strategy.min_models === 1 ? "选择 1 个接入模型" : "选择 2 至 30 个接入模型" }}</span>
        </article>
      </div>
      <p class="strategy-note">当前仅支持管理配置及模拟选择；真实网关调度、轮询计数器和延迟采集尚未接通。</p>
    </div>
  </div>
</template>

<style scoped>
.strategy-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
h2{margin:0 0 8px;font-size:20px}h3{margin:0 0 10px;font-size:16px}
p{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.strategy-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin-top:24px}
.strategy-card{padding:20px;border:1px solid #d8e1e9;border-radius:12px;background:#fbfdfc}
.strategy-card span{display:inline-block;margin-top:18px;color:#176c61;font-size:12px}
.strategy-state{margin-top:24px;padding:32px;text-align:center;color:#64748b}
.strategy-note{margin-top:20px}
</style>
