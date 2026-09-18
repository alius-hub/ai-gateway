<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";

const route = useRoute();

const title = computed(() => String(route.meta.title ?? "未命名页面"));
const description = computed(() =>
  String(route.meta.description ?? "该页面骨架已创建，可继续补充表格、表单和业务交互。"),
);
</script>

<template>
  <section class="page-card">
    <div class="page-card__badge">{{ route.meta.section ?? "模块页面" }}</div>
    <h1 class="page-card__title">{{ title }}</h1>
    <p class="page-card__description">{{ description }}</p>
  </section>
</template>
