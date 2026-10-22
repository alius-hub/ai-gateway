<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from "vue";

withDefaults(defineProps<{ kind?: "capacity" | "output" }>(), { kind: "capacity" });
const panel = ref<HTMLDetailsElement | null>(null);
const tooltip = ref<HTMLElement | null>(null);
const opened = ref(false);
const position = ref({ left: '0px', top: '0px' });
function close() {
  if (panel.value) panel.value.open = false;
  opened.value = false;
}
async function toggleHelp() {
  opened.value = panel.value?.open ?? false;
  if (!opened.value) return;
  await nextTick();
  if (!panel.value || !tooltip.value) return;
  const anchor = panel.value.getBoundingClientRect();
  const box = tooltip.value.getBoundingClientRect();
  const left = Math.max(12, Math.min(anchor.left, window.innerWidth - box.width - 12));
  const top = anchor.bottom + box.height + 20 <= window.innerHeight
    ? anchor.bottom + 8 : Math.max(12, anchor.top - box.height - 8);
  position.value = { left: `${left}px`, top: `${top}px` };
}
function closeOutside(event: MouseEvent) {
  if (event.target instanceof Node && panel.value && !panel.value.contains(event.target)
      && !tooltip.value?.contains(event.target)) {
    close();
  }
}
onMounted(() => {
  document.addEventListener("click", closeOutside, true);
  window.addEventListener("resize", close);
  document.addEventListener("scroll", close, true);
});
onUnmounted(() => {
  document.removeEventListener("click", closeOutside, true);
  window.removeEventListener("resize", close);
  document.removeEventListener("scroll", close, true);
});

function closeHelp(event: KeyboardEvent) {
  if (event.currentTarget instanceof HTMLDetailsElement) {
    event.currentTarget.open = false;
    opened.value = false;
  }
}
</script>

<template>
  <details ref="panel" class="token-help" @toggle="toggleHelp" @keydown.esc="closeHelp">
    <summary :aria-label="kind === 'output' ? '查看最大输出 Token 说明' : '查看最大 Token 容量说明'">!</summary>
  </details>
  <Teleport to="body">
    <span v-if="opened" ref="tooltip" class="token-help__text" :style="position" role="note">
      <template v-if="kind === 'output'">最大输出 Token 表示该接入模型单次回复允许输出的最大 Token 数量。请求的 max_tokens 超过此值时，该模型不会接受本次调用；留空表示网关不额外限制，实际上游模型仍有自身限制。</template>
      <template v-else>最大 Token 容量表示该节点可容纳的最大 Token 数量。请按节点实际能力填写；“最大输出 Token”用于单独限制一次回复的输出长度。</template>
    </span>
  </Teleport>
</template>

<style scoped>
.token-help{position:relative;display:inline-block;flex:0 0 auto;vertical-align:middle;margin-left:4px;text-align:left;font-weight:400;line-height:1}
summary{box-sizing:border-box;display:flex;align-items:center;justify-content:center;width:12px;height:12px;min-width:0;min-height:0;padding:0;border:1px solid #8399a4;border-radius:50%;color:#527582;font-size:9px;line-height:1;font-weight:600;cursor:pointer;list-style:none}
summary::-webkit-details-marker{display:none}
summary:hover,summary:focus-visible{color:#167c70;border-color:#167c70;outline:2px solid #167c7030;outline-offset:2px}
.token-help__text{position:fixed;z-index:10000;box-sizing:border-box;width:280px;max-width:calc(100vw - 24px);padding:12px;border:1px solid #dbe5e9;border-radius:9px;background:#fff;box-shadow:0 6px 20px #17384820;color:#42596a;font-size:12px;line-height:1.7;text-align:left;font-weight:400;white-space:normal;overflow-wrap:anywhere}
</style>
