<script setup lang="ts">
import { ref } from "vue";

import AppFilterDialog from "@/AppFilterDialog.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import { t } from "@/i18n";
import type { FilterField, FilterGroup } from "@/types/filter";

defineProps<{ fields: FilterField[]; modelValue: FilterGroup; hideTags?: boolean }>();
const emit = defineEmits<{ apply: [value: FilterGroup] }>();
const open = ref(false);

function apply(value: FilterGroup) {
  open.value = false;
  emit("apply", value);
}

</script>

<template>
  <div class="list-filter">
    <button class="app-control-button list-filter__trigger" :class="{ 'is-active': modelValue.conditions.length }" type="button" :aria-label="t('高级筛选')" :title="t('高级筛选')" @click="open = true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h16l-6.5 7.5V19l-3 1.5v-8L4 5Z" /></svg>
      <span v-if="modelValue.conditions.length">{{ modelValue.conditions.length }}</span>
    </button>
    <AppFilterDialog :open="open" :fields="fields" :model-value="modelValue" @close="open = false" @apply="apply" />
  </div>
  <AppFilterTags v-if="!hideTags" :fields="fields" :model-value="modelValue" @apply="apply" />
</template>

<style scoped>
.list-filter { display:inline-flex; }
.list-filter__trigger { gap:5px; padding:6px 9px; }
.list-filter__trigger svg { width:18px; height:18px; }
.list-filter__trigger.is-active { background:#217c70; color:#fff; border-color:#217c70; }
.list-filter__trigger.is-active:hover { background:#176d62; color:#fff; }
</style>
