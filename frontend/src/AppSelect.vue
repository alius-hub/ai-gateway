<script setup lang="ts">
import { ElOption, ElSelect } from "element-plus";

export type SelectValue = string | number;
export interface SelectOption {
  label: string;
  value: SelectValue;
  disabled?: boolean;
}

defineProps<{
  modelValue?: SelectValue | null;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  ariaLabel?: string;
}>();

const emit = defineEmits<{
  "update:modelValue": [value: SelectValue];
  change: [value: SelectValue];
}>();
</script>

<template>
  <ElSelect
    class="app-select"
    :model-value="modelValue"
    :placeholder="placeholder"
    :disabled="disabled"
    :aria-label="ariaLabel"
    popper-class="app-select-popper"
    @update:model-value="emit('update:modelValue', $event as SelectValue)"
    @change="emit('change', $event as SelectValue)"
  >
    <ElOption v-for="option in options" :key="option.value" :value="option.value" :label="option.label" :disabled="option.disabled" />
  </ElSelect>
</template>
