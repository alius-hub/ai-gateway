<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppSelect from "@/AppSelect.vue";
import { t } from "@/i18n";
import type { FilterCondition, FilterField, FilterGroup, FilterOperator } from "@/types/filter";

const props = defineProps<{ fields: FilterField[]; modelValue: FilterGroup; open: boolean }>();
const emit = defineEmits<{ close: []; apply: [value: FilterGroup] }>();
const draft = ref<FilterGroup>({ mode: "and", conditions: [] });
const operators: Record<FilterField["type"], { label: string; value: FilterOperator }[]> = {
  text: [
    { label: "包含", value: "contains" }, { label: "等于", value: "eq" },
    { label: "不等于", value: "ne" },
  ],
  number: [
    { label: "等于", value: "eq" }, { label: "不等于", value: "ne" },
    { label: "大于", value: "gt" }, { label: "大于等于", value: "gte" },
    { label: "小于", value: "lt" }, { label: "小于等于", value: "lte" },
  ],
  decimal: [
    { label: "等于", value: "eq" }, { label: "不等于", value: "ne" },
    { label: "大于", value: "gt" }, { label: "大于等于", value: "gte" },
    { label: "小于", value: "lt" }, { label: "小于等于", value: "lte" },
  ],
  date: [
    { label: "等于", value: "eq" }, { label: "早于", value: "lt" },
    { label: "不早于", value: "gte" },
  ],
  select: [{ label: "等于", value: "eq" }, { label: "不等于", value: "ne" }],
};
const valid = computed(() => draft.value.conditions.every((condition) => {
  const field = props.fields.find((item) => item.key === condition.field);
  return field && operators[field.type].some((item) => item.value === condition.operator)
    && condition.value.trim() !== ""
    && (field.type !== "number" || (/^\d+$/.test(condition.value) && Number.isSafeInteger(Number(condition.value))))
    && (field.type !== "decimal" || /^\d+(\.\d+)?$/.test(condition.value))
    && (field.type !== "date" || /^\d{4}-\d{2}-\d{2}$/.test(condition.value));
}));

watch(() => props.open, (open) => {
  if (open) draft.value = {
    mode: props.modelValue.mode,
    conditions: props.modelValue.conditions.map((condition) => ({ ...condition })),
  };
});

function fieldFor(condition: FilterCondition) {
  return props.fields.find((field) => field.key === condition.field) ?? props.fields[0];
}

function add() {
  const field = props.fields[0];
  if (field && draft.value.conditions.length < 8) {
    draft.value.conditions.push({ field: field.key, operator: operators[field.type][0].value, value: "" });
  }
}

function changeField(condition: FilterCondition, value: string | number) {
  condition.field = String(value);
  condition.operator = operators[fieldFor(condition).type][0].value;
  condition.value = "";
}

function submit() {
  if (!valid.value) return;
  emit("apply", {
    mode: draft.value.mode,
    conditions: draft.value.conditions.map((condition) => ({
      ...condition, value: condition.value.trim(),
    })),
  });
}
</script>

<template>
  <div v-if="open" class="app-modal-overlay" @click.self="emit('close')">
    <form class="app-modal-panel filter-dialog" role="dialog" aria-modal="true" :aria-label="t('高级筛选')" @submit.prevent="submit">
      <header><h2>{{ t("高级筛选") }}</h2><button class="app-control-button app-control-button--icon" type="button" :aria-label="t('关闭')" @click="emit('close')">×</button></header>
      <div class="filter-dialog__mode">
        <span>{{ t("匹配方式") }}</span>
        <AppSelect :model-value="draft.mode" :options="[{ label: t('全部条件 (AND)'), value: 'and' }, { label: t('任一条件 (OR)'), value: 'or' }]" :aria-label="t('匹配方式')" @update:model-value="draft.mode = $event === 'or' ? 'or' : 'and'" />
      </div>
      <div class="filter-dialog__conditions">
        <div v-for="(condition, index) in draft.conditions" :key="index" class="filter-dialog__condition">
          <AppSelect :model-value="condition.field" :options="fields.map((field) => ({ label: t(field.label), value: field.key }))" :aria-label="t('筛选字段')" @update:model-value="changeField(condition, $event)" />
          <AppSelect :model-value="condition.operator" :options="operators[fieldFor(condition).type].map((operator) => ({ label: t(operator.label), value: operator.value }))" :aria-label="t('运算符')" @update:model-value="condition.operator = $event as FilterOperator" />
          <AppSelect v-if="fieldFor(condition).type === 'select'" v-model="condition.value" :options="(fieldFor(condition).options ?? []).map((option) => ({ label: t(option.label), value: option.value }))" :placeholder="t('请选择')" :aria-label="t('筛选值')" />
          <input v-else :value="condition.value" class="app-control-input" :type="fieldFor(condition).type === 'date' ? 'date' : ['number', 'decimal'].includes(fieldFor(condition).type) ? 'number' : 'text'" :min="['number', 'decimal'].includes(fieldFor(condition).type) ? 0 : undefined" :step="fieldFor(condition).type === 'decimal' ? 'any' : undefined" :placeholder="t('输入筛选值')" :aria-label="t('筛选值')" @input="condition.value = ($event.target as HTMLInputElement).value" />
          <button class="app-control-button app-control-button--icon" type="button" :aria-label="t('删除条件')" @click="draft.conditions.splice(index, 1)">×</button>
        </div>
        <p v-if="!draft.conditions.length">{{ t("暂无条件，添加一条开始筛选") }}</p>
      </div>
      <button class="app-control-button app-control-button--add" type="button" :disabled="draft.conditions.length >= 8" @click="add">
        <span class="filter-dialog__add-icon" aria-hidden="true">+</span>
        {{ t("添加条件") }}
      </button>
      <footer>
        <button class="app-control-button app-control-button--soft filter-dialog__reset" type="button" @click="draft.conditions = []; draft.mode = 'and'">{{ t("重置") }}</button>
        <button class="app-control-button" type="button" @click="emit('close')">{{ t("取消") }}</button>
        <button class="app-control-button app-control-button--primary" type="button" :disabled="!valid" @click="submit">{{ t("应用筛选") }}</button>
      </footer>
    </form>
  </div>
</template>

<style scoped>
.filter-dialog { width:min(740px,100%); padding:24px; }
.filter-dialog header,.filter-dialog footer { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.filter-dialog h2 { margin:0; font-size:18px; }
.filter-dialog__mode { display:flex; align-items:center; gap:12px; margin:24px 0 16px; font-size:13px; }
.filter-dialog__mode .app-select { width:185px; }
.filter-dialog__conditions { display:grid; gap:10px; margin-bottom:14px; }
.filter-dialog__conditions p { margin:0; padding:18px; background:#f7f9fa; border-radius:9px; }
.filter-dialog__condition { display:grid; grid-template-columns:minmax(130px,1.3fr) minmax(105px,1fr) minmax(150px,1.5fr) 34px; gap:8px; align-items:center; }
.filter-dialog__condition .app-select { min-width:0; width:100%; }
.filter-dialog__add-icon { display:grid; place-items:center; width:20px; height:20px; border-radius:6px; background:#d9f1e9; font-size:18px; font-weight:500; line-height:1; }
.filter-dialog footer { justify-content:flex-end; margin-top:24px; }
.filter-dialog__reset { margin-right:auto; }
@media (max-width:600px) {
  .filter-dialog__condition { grid-template-columns:1fr 1fr 34px; }
  .filter-dialog__condition :nth-child(3) { grid-column:1 / 3; grid-row:2; }
  .filter-dialog__condition button { grid-column:3; grid-row:1 / 3; }
  .filter-dialog footer { flex-wrap:wrap; }
}
</style>
