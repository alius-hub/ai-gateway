<script setup lang="ts">
import { computed } from "vue";

const props = defineProps<{
  points: { date: string; value: number | null }[];
  title: string;
  unit?: string;
  digits?: number;
}>();

const width = computed(() => Math.max(640, props.points.length * 29 + 56));
const maxValue = computed(() => Math.max(1, ...props.points.map((p) => p.value ?? 0)));
const coords = computed(() => props.points.map((point, index) => ({
  ...point,
  x: 36 + index * (width.value - 70) / Math.max(1, props.points.length - 1),
  y: 170 - (point.value ?? 0) / maxValue.value * 135,
})));
const segments = computed(() => {
  const result: string[] = [];
  let current = "";
  for (const point of coords.value) {
    if (point.value === null) {
      if (current) result.push(current);
      current = "";
    } else {
      current += `${current ? " " : ""}${point.x},${point.y}`;
    }
  }
  if (current) result.push(current);
  return result;
});
const dateStep = computed(() => Math.max(1, Math.ceil(props.points.length / 9)));
function formatted(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: props.digits ?? 2,
  }).format(value);
}
</script>

<template>
  <div class="analytics-trend" role="img" :aria-label="`${title}，按 UTC 日期展示`">
    <div v-if="!points.some((p) => p.value !== null)" class="analytics-trend__empty">暂无可用数据</div>
    <div v-else class="analytics-trend__scroll">
      <svg :viewBox="`0 0 ${width} 216`" :style="{ minWidth: `${width}px` }" aria-hidden="true">
        <g v-for="step in [0, 1, 2, 3]" :key="step">
          <line x1="36" :x2="width - 24" :y1="35 + step * 45" :y2="35 + step * 45"
            stroke="#e4edef" stroke-dasharray="4 4" />
          <text x="2" :y="39 + step * 45" class="analytics-trend__axis">
            {{ formatted(maxValue * (3 - step) / 3) }}
          </text>
        </g>
        <polyline v-for="(segment, index) in segments" :key="index" :points="segment"
          fill="none" stroke="#218a79" stroke-width="2.5" stroke-linejoin="round" />
        <g v-for="(point, index) in coords" :key="point.date">
          <circle v-if="point.value !== null" :cx="point.x" :cy="point.y" r="4"
            fill="#fff" stroke="#218a79" stroke-width="2">
            <title>{{ point.date }}: {{ formatted(point.value) }}{{ unit || "" }}</title>
          </circle>
          <text v-if="index % dateStep === 0 || index === points.length - 1"
            :x="point.x" y="204" text-anchor="middle" class="analytics-trend__axis">
            {{ point.date.slice(5) }}
          </text>
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.analytics-trend { width: 100%; min-height: 220px; }
.analytics-trend__scroll { overflow-x: auto; }
.analytics-trend svg { display: block; width: 100%; height: 216px; }
.analytics-trend__axis { fill: #748696; font-size: 10px; }
.analytics-trend__empty { display: grid; place-items: center; min-height: 220px; color: #8796a3; font-size: 13px; }
</style>
