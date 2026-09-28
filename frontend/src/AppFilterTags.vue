<script setup lang="ts">
import { t } from "@/i18n";
import type { FilterCondition, FilterField, FilterGroup } from "@/types/filter";

const props = defineProps<{ fields: FilterField[]; modelValue: FilterGroup }>();
const emit = defineEmits<{ apply: [value: FilterGroup] }>();
const operators = {
  contains: "包含", eq: "等于", ne: "不等于", gt: "大于",
  gte: "大于等于", lt: "小于", lte: "小于等于",
};

function label(condition: FilterCondition) {
  const field = props.fields.find((item) => item.key === condition.field);
  const value = field?.options?.find((option) => option.value === condition.value)?.label ?? condition.value;
  return `${t(field?.label ?? condition.field)} ${t(operators[condition.operator])} ${t(value)}`;
}

function remove(index: number) {
  emit("apply", {
    ...props.modelValue,
    conditions: props.modelValue.conditions.filter((_, position) => position !== index),
  });
}
</script>

<template>
  <div v-if="modelValue.conditions.length" class="list-filter__tags">
    <span>{{ t(modelValue.mode === "and" ? "满足全部条件" : "满足任一条件") }}</span>
    <button v-for="(condition, index) in modelValue.conditions" :key="index" class="app-control-button" type="button" :aria-label="`${t('移除筛选')} ${label(condition)}`" @click="remove(index)">
      {{ label(condition) }} ×
    </button>
    <button class="app-control-button app-control-button--soft" type="button" @click="emit('apply', { mode: 'and', conditions: [] })">{{ t("清除全部") }}</button>
  </div>
</template>

<style scoped>
.list-filter__tags { display:flex; align-items:center; flex-wrap:wrap; gap:8px; box-sizing:border-box; width:100%; min-width:0; max-width:100%; flex:0 0 100%; order:1; padding:12px 0; font-size:12px; color:#607685; }
.list-filter__tags button { max-width:100%; min-height:28px; padding:4px 9px; overflow-wrap:anywhere; font-size:12px; }
</style>
