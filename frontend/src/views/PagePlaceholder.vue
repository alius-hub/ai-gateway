<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "@/i18n";

const route = useRoute();

const description = computed(() =>
  t(String(route.meta.description ?? "该功能正在规划中。")),
);
</script>

<template>
  <section class="page-stack planned-page">
    <div class="page-heading">
      <p class="page-card__description">{{ description }}</p>
    </div>

    <div class="page-card planned-panel">
      <span class="planned-panel__icon" aria-hidden="true">
        <svg viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="6" y="9" width="28" height="23" rx="4" />
          <path d="M6 16h28M13 24h6M13 28h12M12 5v4M28 5v4" />
        </svg>
      </span>
      <span class="planned-panel__eyebrow">COMING SOON</span>
      <h2>{{ t("功能建设中") }}</h2>
      <p>{{ t("该模块尚未开放，目前没有可操作的内容。") }}</p>
    </div>
  </section>
</template>

<style scoped>
.planned-panel {
  display: flex;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  min-height: 340px;
  padding: 44px 24px;
  text-align: center;
}

.planned-panel__icon {
  display: grid;
  place-items: center;
  width: 68px;
  height: 68px;
  margin-bottom: 22px;
  border: 1px solid #cce8df;
  border-radius: 18px;
  background: #eff8f5;
  color: #319c85;
}

.planned-panel__icon svg {
  width: 34px;
  height: 34px;
}

.planned-panel__eyebrow {
  color: #429b86;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.17em;
}

.planned-panel h2 {
  margin: 12px 0 8px;
  color: #233a48;
  font-size: 19px;
}

.planned-panel p {
  margin: 0;
  color: #8192a0;
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 560px) {
  .planned-panel {
    min-height: 300px;
  }
}
</style>
