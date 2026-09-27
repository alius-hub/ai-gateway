<script setup lang="ts">
import { t } from "@/i18n";
import { activeToast, dismissToast } from "@/utils/toast";

const titles = { success: "操作成功", error: "操作失败", info: "提示" };
</script>

<template>
  <Teleport to="body">
    <div class="toast-host">
      <Transition name="toast">
        <div
          v-if="activeToast"
          :key="activeToast.id"
          class="toast-card"
          :class="`toast-card--${activeToast.type}`"
          :role="activeToast.type === 'error' ? 'alert' : 'status'"
        >
          <span class="toast-card__icon" aria-hidden="true">
            <svg v-if="activeToast.type === 'success'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 6" /></svg>
            <svg v-else-if="activeToast.type === 'error'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 7v6m0 4h.01" /><circle cx="12" cy="12" r="9" /></svg>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 11v6m0-10h.01" /><circle cx="12" cy="12" r="9" /></svg>
          </span>
          <div class="toast-card__content">
            <strong>{{ t(titles[activeToast.type]) }}</strong>
            <span>{{ activeToast.text }}</span>
          </div>
          <button type="button" class="toast-card__close" :aria-label="t('关闭通知')" @click="dismissToast">×</button>
        </div>
      </Transition>
    </div>
  </Teleport>
</template>

<style scoped>
.toast-host {
  position: fixed;
  z-index: 100;
  top: 20px;
  left: 50%;
  width: min(440px, calc(100vw - 32px));
  transform: translateX(-50%);
  pointer-events: none;
}

.toast-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 15px;
  border: 1px solid #d8e9e5;
  border-radius: 13px;
  background: #fff;
  box-shadow: 0 14px 42px rgba(17, 37, 50, 0.18);
  color: #24483f;
  pointer-events: auto;
}

.toast-card--success { border-color: #b7e4d2; background: #f6fcf9; color: #18775e; }
.toast-card--error { border-color: #f1cfc8; background: #fff9f7; color: #a64d41; }
.toast-card--info { border-color: #c9dfe9; background: #f8fbfd; color: #376b82; }

.toast-card__icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: none;
  border-radius: 8px;
  background: currentColor;
}

.toast-card__icon svg {
  width: 17px;
  height: 17px;
  color: #fff;
}

.toast-card__content { display: grid; gap: 4px; min-width: 0; flex: 1; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
.toast-card__content strong { font-size: 13px; }
.toast-card__content span { color: #465a62; }
.toast-card__close { flex: none; border: 0; background: transparent; color: #82949b; font-size: 22px; line-height: 1; cursor: pointer; }
.toast-card__close:hover { color: #263d48; }
.toast-card__close:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; border-radius: 3px; }

.toast-enter-active, .toast-leave-active { transition: opacity 180ms ease, transform 180ms ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(-12px); }

@media (prefers-reduced-motion: reduce) {
  .toast-enter-active, .toast-leave-active { transition: none; }
}
</style>
