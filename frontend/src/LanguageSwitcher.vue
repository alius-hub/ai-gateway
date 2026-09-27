<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from "vue";

import { locale, type Locale } from "@/i18n";

const languages: Array<{ value: Locale; label: string; detail: string }> = [
  { value: "zh-CN", label: "简体中文", detail: "Chinese" },
  { value: "en-US", label: "English", detail: "英语" },
];
const open = ref(false);
const root = ref<HTMLElement | null>(null);
const trigger = ref<HTMLButtonElement | null>(null);
const options = ref<HTMLButtonElement[]>([]);

async function showMenu() {
  open.value = true;
  await nextTick();
  options.value[languages.findIndex((item) => item.value === locale.value)]?.focus();
}

function closeMenu(restoreFocus = false) {
  open.value = false;
  if (restoreFocus) trigger.value?.focus();
}

function selectLanguage(value: Locale) {
  locale.value = value;
  closeMenu(true);
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && open.value) {
    event.stopPropagation();
    closeMenu(true);
    return;
  }
  if (!open.value || !["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const current = options.value.indexOf(document.activeElement as HTMLButtonElement);
  const next = event.key === "Home" ? 0 : event.key === "End" ? options.value.length - 1
    : (current + (event.key === "ArrowDown" ? 1 : -1) + options.value.length) % options.value.length;
  options.value[next]?.focus();
}

function onOutsideClick(event: PointerEvent) {
  if (open.value && !root.value?.contains(event.target as Node)) closeMenu();
}

function onFocusout(event: FocusEvent) {
  if (open.value && !root.value?.contains(event.relatedTarget as Node | null)) closeMenu();
}

onMounted(() => window.addEventListener("pointerdown", onOutsideClick));
onUnmounted(() => window.removeEventListener("pointerdown", onOutsideClick));
</script>

<template>
  <div ref="root" class="language-switcher" @keydown="onKeydown" @focusout="onFocusout">
    <button
      ref="trigger"
      type="button"
      class="language-switcher__trigger"
      :aria-label="locale === 'zh-CN' ? '选择语言' : 'Select language'"
      aria-haspopup="true"
      aria-controls="language-options"
      :aria-expanded="open"
      @click="open ? closeMenu() : showMenu()"
    >
      <svg class="language-switcher__globe" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c-2.5 2.5-3.5 5.5-3.5 9s1 6.5 3.5 9M12 3c2.5 2.5 3.5 5.5 3.5 9s-1 6.5-3.5 9" />
      </svg>
      <span>{{ languages.find((item) => item.value === locale)?.label }}</span>
      <svg class="language-switcher__chevron" :class="{ 'is-open': open }" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="m5 7 5 5 5-5" />
      </svg>
    </button>
    <div v-if="open" id="language-options" class="language-switcher__menu" role="group" :aria-label="locale === 'zh-CN' ? '选择语言' : 'Select language'">
      <button
        v-for="item in languages"
        :key="item.value"
        :ref="(element) => { if (element) options[languages.indexOf(item)] = element as HTMLButtonElement; }"
        type="button"
        class="language-switcher__option"
        :class="{ 'is-selected': locale === item.value }"
        :aria-pressed="locale === item.value"
        @click="selectLanguage(item.value)"
      >
        <span class="language-switcher__option-copy">
          <span>{{ item.label }}</span>
          <small>{{ item.detail }}</small>
        </span>
        <svg v-if="locale === item.value" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="m4 10 4 4 8-8" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.language-switcher {
  position: relative;
  z-index: 10;
  flex: none;
  margin-left: auto;
}

.language-switcher__trigger {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 38px;
  padding: 0 11px;
  border: 1px solid #dce6e9;
  border-radius: 10px;
  background: #fff;
  color: #244956;
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease, box-shadow 160ms ease;
}

.language-switcher__trigger:hover,
.language-switcher__trigger[aria-expanded="true"] {
  border-color: #90c9bd;
  background: #f6fcfa;
  box-shadow: 0 0 0 3px rgba(49, 143, 132, 0.08);
}

.language-switcher__trigger svg {
  width: 16px;
  height: 16px;
  flex: none;
}

.language-switcher__globe {
  color: #318f84;
}

.language-switcher__chevron {
  color: #7b929b;
  transition: transform 160ms ease;
}

.language-switcher__chevron.is-open {
  transform: rotate(180deg);
}

.language-switcher__menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  width: 176px;
  padding: 6px;
  border: 1px solid #e0eae9;
  border-radius: 12px;
  background: #fff;
  box-shadow: 0 14px 35px rgba(22, 43, 60, 0.14);
}

.language-switcher__option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 48px;
  padding: 7px 10px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #344b59;
  font: inherit;
  font-size: 12px;
  text-align: left;
  cursor: pointer;
}

.language-switcher__option:hover,
.language-switcher__option:focus-visible {
  background: #f1f8f6;
}

.language-switcher__option.is-selected {
  background: #e9f6f2;
  color: #176c61;
}

.language-switcher__option-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.language-switcher__option-copy small {
  color: #8398a0;
  font-size: 10px;
}

.language-switcher__option svg {
  width: 16px;
  height: 16px;
  color: #218576;
}

.language-switcher__trigger:focus-visible,
.language-switcher__option:focus-visible {
  outline: 2px solid #318f84;
  outline-offset: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .language-switcher__trigger,
  .language-switcher__chevron {
    transition: none;
  }
}
</style>
