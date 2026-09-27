<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppSelect, { type SelectOption } from "@/AppSelect.vue";
import { t } from "@/i18n";

const props = withDefaults(defineProps<{
  modelValue: number;
  total: number;
  pageSize?: number;
  pageSizeOptions?: number[];
  maxVisiblePages?: number;
  disabled?: boolean;
}>(), {
  pageSize: 20,
  pageSizeOptions: () => [10, 20, 50, 100],
  maxVisiblePages: 5,
  disabled: false,
});

const emit = defineEmits<{
  "update:modelValue": [value: number];
  "update:pageSize": [value: number];
  change: [value: number];
}>();

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const currentPage = computed(() => clamp(props.modelValue));
const jumpPage = ref(String(currentPage.value));
const pageSizeOptions = computed<SelectOption[]>(() => props.pageSizeOptions.map((value) => ({
  label: t(`${value} 条/页`),
  value,
})));

const visiblePages = computed<(number | string)[]>(() => {
  const totalPageCount = totalPages.value;
  const maxVisible = Math.max(3, props.maxVisiblePages);

  if (totalPageCount <= maxVisible + 2) {
    return Array.from({ length: totalPageCount }, (_, index) => index + 1);
  }

  const middleSize = Math.max(1, maxVisible - 2);
  let start = Math.max(2, currentPage.value - Math.floor(middleSize / 2));
  let end = Math.min(totalPageCount - 1, start + middleSize - 1);

  start = Math.max(2, end - middleSize + 1);

  const pages: Array<number | string> = [1];
  if (start > 2) pages.push("start-ellipsis");
  for (let page = start; page <= end; page += 1) pages.push(page);
  if (end < totalPageCount - 1) pages.push("end-ellipsis");
  pages.push(totalPageCount);

  return pages;
});

watch([() => props.modelValue, totalPages], () => {
  jumpPage.value = String(currentPage.value);
}, { immediate: true });

function clamp(page: number) {
  if (!Number.isFinite(page)) return 1;
  return Math.min(Math.max(Math.trunc(page), 1), totalPages.value);
}

function updatePage(page: number) {
  if (props.disabled) return;

  const nextPage = clamp(page);
  if (nextPage === props.modelValue) {
    jumpPage.value = String(nextPage);
    return;
  }

  emit("update:modelValue", nextPage);
  emit("change", nextPage);
}

function submitJump() {
  const target = Number(jumpPage.value.trim());
  if (!Number.isFinite(target)) {
    jumpPage.value = String(currentPage.value);
    return;
  }

  updatePage(target);
}

function updatePageSize(value: string | number) {
  if (props.disabled) return;

  const nextPageSize = Number(value);
  if (!Number.isFinite(nextPageSize) || nextPageSize <= 0 || nextPageSize === props.pageSize) return;

  emit("update:pageSize", nextPageSize);
}
</script>

<template>
  <nav class="app-pagination" :aria-label="t('分页导航')">
    <div class="app-pagination__summary">
      <strong>{{ total }}</strong>
      <span>{{ t(`条记录 · 第 ${currentPage} / ${totalPages} 页`) }}</span>
    </div>

    <div class="app-pagination__controls">
      <button type="button" class="app-pagination__ghost" :disabled="disabled || currentPage <= 1" @click="updatePage(1)">
        {{ t("首页") }}
      </button>
      <button type="button" class="app-pagination__ghost" :disabled="disabled || currentPage <= 1" @click="updatePage(currentPage - 1)">
        {{ t("上一页") }}
      </button>

      <div class="app-pagination__pages">
        <template v-for="(pageItem, index) in visiblePages" :key="`${pageItem}-${index}`">
          <span v-if="typeof pageItem === 'string'" class="app-pagination__ellipsis">...</span>
          <button
            v-else
            type="button"
            class="app-pagination__page"
            :class="{ 'is-active': pageItem === currentPage }"
            :disabled="disabled"
            @click="updatePage(pageItem)"
          >
            {{ pageItem }}
          </button>
        </template>
      </div>

      <button type="button" class="app-pagination__ghost" :disabled="disabled || currentPage >= totalPages" @click="updatePage(currentPage + 1)">
        {{ t("下一页") }}
      </button>
      <button type="button" class="app-pagination__ghost" :disabled="disabled || currentPage >= totalPages" @click="updatePage(totalPages)">
        {{ t("末页") }}
      </button>
    </div>

    <div class="app-pagination__tools">
      <label class="app-pagination__size">
        <span>{{ t("每页") }}</span>
        <AppSelect
          class="app-pagination__select"
          :model-value="pageSize"
          :options="pageSizeOptions"
          :disabled="disabled"
          :aria-label="t('选择每页条数')"
          @update:model-value="updatePageSize"
        />
      </label>

      <form class="app-pagination__jump" @submit.prevent="submitJump">
        <label class="app-pagination__jump-label">
          <span>{{ t("跳转到") }}</span>
          <input
            v-model="jumpPage"
            type="number"
            min="1"
            :max="totalPages"
            inputmode="numeric"
            :disabled="disabled"
            :aria-label="t('输入页码')"
          />
        </label>
        <button type="submit" class="app-pagination__confirm" :disabled="disabled">
          {{ t("跳转") }}
        </button>
      </form>
    </div>
  </nav>
</template>

<style scoped>
.app-pagination {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 24px 22px;
  border-top: 1px solid #edf1f3;
  background: linear-gradient(180deg, #fcfefd, #f6fbf9);
}

.app-pagination__summary {
  display: flex;
  flex: 1 1 0;
  align-items: baseline;
  gap: 8px;
  color: #738793;
  font-size: 12px;
  white-space: nowrap;
}

.app-pagination__summary strong {
  color: #1b3a46;
  font-size: 18px;
  font-weight: 700;
}

.app-pagination__controls,
.app-pagination__pages,
.app-pagination__tools,
.app-pagination__size,
.app-pagination__jump,
.app-pagination__jump-label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.app-pagination__controls {
  justify-content: center;
}

.app-pagination__pages {
  flex-wrap: wrap;
}

.app-pagination__tools {
  flex: 1 1 0;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.app-pagination__ghost,
.app-pagination__page,
.app-pagination__confirm {
  min-width: 36px;
  min-height: 36px;
  padding: 0 12px;
  border: 1px solid #d6e5e3;
  border-radius: 10px;
  background: #fff;
  color: #2c4652;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, color 160ms ease, box-shadow 160ms ease;
}

.app-pagination__page {
  padding: 0 10px;
}

.app-pagination__ghost:hover:not(:disabled),
.app-pagination__page:hover:not(:disabled),
.app-pagination__confirm:hover:not(:disabled) {
  border-color: #91c7bc;
  background: #eff8f5;
  color: #176c61;
}

.app-pagination__page.is-active,
.app-pagination__confirm {
  border-color: #167e70;
  background: #167e70;
  color: #fff;
}

.app-pagination__page.is-active:hover:not(:disabled),
.app-pagination__confirm:hover:not(:disabled) {
  border-color: #10695e;
  background: #10695e;
}

.app-pagination__ghost:disabled,
.app-pagination__page:disabled,
.app-pagination__confirm:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.app-pagination__ellipsis {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  color: #9aadb7;
  font-size: 14px;
}

.app-pagination__size,
.app-pagination__jump-label {
  color: #5f7480;
  font-size: 12px;
  white-space: nowrap;
}

.app-pagination__size {
  gap: 10px;
}

.app-pagination__select {
  width: 116px;
}

.app-pagination__jump {
  flex-wrap: wrap;
}

.app-pagination__jump input {
  width: 72px;
  min-height: 36px;
  padding: 8px 10px;
  border: 1px solid #d6e3e5;
  border-radius: 10px;
  background: #fff;
  color: #29414d;
  font: inherit;
  font-size: 12px;
  text-align: center;
  outline: none;
}

.app-pagination__jump input:focus {
  border-color: #42aa98;
  box-shadow: 0 0 0 3px #e2f5ee;
}

.app-pagination__ghost:focus-visible,
.app-pagination__page:focus-visible,
.app-pagination__confirm:focus-visible,
.app-pagination__jump input:focus-visible {
  outline: 2px solid #3f9f91;
  outline-offset: 2px;
}

@media (max-width: 960px) {
  .app-pagination {
    align-items: stretch;
    flex-direction: column;
  }

  .app-pagination__summary,
  .app-pagination__controls,
  .app-pagination__tools {
    width: 100%;
  }

  .app-pagination__controls {
    justify-content: center;
    flex-wrap: wrap;
  }

  .app-pagination__pages {
    order: 1;
    width: auto;
    justify-content: center;
  }

  .app-pagination__tools {
    justify-content: flex-end;
  }
}

@media (max-width: 560px) {
  .app-pagination {
    padding: 16px 20px 20px;
  }

  .app-pagination__summary {
    flex-wrap: wrap;
    white-space: normal;
  }

  .app-pagination__controls {
    gap: 10px;
  }

  .app-pagination__ghost,
  .app-pagination__confirm {
    flex: 1 1 calc(50% - 5px);
    justify-content: center;
  }

  .app-pagination__pages {
    justify-content: center;
  }

  .app-pagination__jump {
    justify-content: stretch;
  }

  .app-pagination__tools {
    justify-content: stretch;
  }

  .app-pagination__size {
    width: 100%;
    justify-content: space-between;
  }

  .app-pagination__select {
    width: 120px;
  }

  .app-pagination__jump-label {
    flex: 1;
    justify-content: space-between;
  }

  .app-pagination__jump input {
    width: 84px;
  }
}
</style>
