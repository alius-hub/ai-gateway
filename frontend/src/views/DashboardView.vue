<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { fetchOverviewSummary } from "@/api/overview";
import type { OverviewSummary } from "@/types/overview";

const loading = ref(false);
const errorMessage = ref("");
const summary = ref<OverviewSummary | null>(null);

const metrics = computed(() => {
  if (!summary.value) {
    return [];
  }

  return [
    { label: "总调用量", value: formatInteger(summary.value.total_requests), hint: "累计请求次数" },
    { label: "总 Token", value: formatInteger(summary.value.total_tokens), hint: "累计消耗 Token" },
    { label: "总成本", value: formatCurrency(summary.value.total_cost), hint: "累计预估成本" },
    { label: "组织数", value: formatInteger(summary.value.organization_count), hint: "已创建组织" },
    { label: "项目数", value: formatInteger(summary.value.project_count), hint: "已创建项目" },
    { label: "凭证数", value: formatInteger(summary.value.key_count), hint: "可用 API Key 数量" },
    { label: "模型数", value: formatInteger(summary.value.model_count), hint: "接入模型总数" },
    { label: "节点数", value: formatInteger(summary.value.node_count), hint: "节点治理总量" },
  ];
});

const statusItems = computed(() => {
  if (!summary.value) {
    return [];
  }

  return [
    {
      label: "数据库状态",
      value: summary.value.database_status === "connected" ? "已连接" : "未就绪",
    },
    {
      label: "数据来源",
      value: summary.value.data_source === "database" ? "实时数据库" : "启动占位数据",
    },
    {
      label: "健康供应商",
      value: `${formatInteger(summary.value.healthy_provider_count)} / ${formatInteger(summary.value.provider_count)}`,
    },
    {
      label: "活跃节点",
      value: `${formatInteger(summary.value.active_node_count)} / ${formatInteger(summary.value.node_count)}`,
    },
  ];
});

const alignedRequirements = [
  "平台总调用量、Token 消耗和成本总览",
  "组织、项目、凭证、模型、节点等核心资源统计",
  "供应商健康状态与节点活跃度基础视图",
];

function formatInteger(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatCurrency(value: string): string {
  const amount = Number.parseFloat(value);
  if (Number.isNaN(amount)) {
    return value;
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

async function loadSummary() {
  loading.value = true;
  errorMessage.value = "";

  try {
    summary.value = await fetchOverviewSummary();
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "总览数据加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  void loadSummary();
});
</script>

<template>
  <section class="dashboard">
    <div class="page-card dashboard-hero">
      <div>
        <div class="page-card__badge">工作台 / 平台总览</div>
        <h1 class="page-card__title">平台运行总览</h1>
        <p class="page-card__description">
          这一版先把需求文档中的核心总览指标落下来，前端直接消费后端汇总接口，方便我们后续继续扩展趋势图、告警卡片和排行榜。
        </p>
      </div>

      <button class="dashboard-hero__action" type="button" :disabled="loading" @click="loadSummary">
        {{ loading ? "刷新中..." : "刷新数据" }}
      </button>
    </div>

    <div v-if="errorMessage" class="dashboard-error">
      {{ errorMessage }}
    </div>

    <div v-if="summary" class="dashboard-grid">
      <article v-for="item in metrics" :key="item.label" class="dashboard-metric">
        <span class="dashboard-metric__label">{{ item.label }}</span>
        <strong class="dashboard-metric__value">{{ item.value }}</strong>
        <span class="dashboard-metric__hint">{{ item.hint }}</span>
      </article>
    </div>

    <div v-if="summary" class="dashboard-panels">
      <section class="page-card dashboard-panel">
        <h2 class="dashboard-panel__title">系统状态</h2>
        <p class="dashboard-panel__desc">{{ summary.status_message }}</p>

        <div class="dashboard-status-list">
          <div v-for="item in statusItems" :key="item.label" class="dashboard-status-item">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
      </section>

      <section class="page-card dashboard-panel">
        <h2 class="dashboard-panel__title">已对齐需求</h2>
        <p class="dashboard-panel__desc">
          对应 `docs/requirements-aligned-design.md` 中“平台总览”的首批落地项。
        </p>

        <ul class="dashboard-checklist">
          <li v-for="item in alignedRequirements" :key="item">
            {{ item }}
          </li>
        </ul>

        <p class="dashboard-panel__foot">
          数据生成时间：{{ new Date(summary.generated_at).toLocaleString("zh-CN") }}
        </p>
      </section>
    </div>
  </section>
</template>

<style scoped>
.dashboard {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.dashboard-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.dashboard-hero__action {
  padding: 12px 16px;
  border: 0;
  border-radius: 12px;
  background: #1d4ed8;
  color: #eff6ff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.dashboard-hero__action:disabled {
  cursor: not-allowed;
  opacity: 0.7;
}

.dashboard-error {
  padding: 14px 16px;
  border-radius: 14px;
  background: #fee2e2;
  color: #b91c1c;
}

.dashboard-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
}

.dashboard-metric {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 20px;
  border-radius: 18px;
  background: #ffffff;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08);
}

.dashboard-metric__label {
  color: #64748b;
  font-size: 13px;
}

.dashboard-metric__value {
  font-size: 30px;
  line-height: 1.1;
}

.dashboard-metric__hint {
  color: #475569;
  font-size: 13px;
}

.dashboard-panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px;
}

.dashboard-panel__title {
  margin: 0 0 10px;
  font-size: 20px;
}

.dashboard-panel__desc {
  margin: 0 0 18px;
  color: #475569;
  line-height: 1.7;
}

.dashboard-status-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.dashboard-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #f8fafc;
}

.dashboard-checklist {
  margin: 0;
  padding-left: 20px;
  color: #334155;
  line-height: 1.8;
}

.dashboard-panel__foot {
  margin: 18px 0 0;
  color: #64748b;
  font-size: 13px;
}

@media (max-width: 960px) {
  .dashboard-hero {
    flex-direction: column;
  }
}
</style>
