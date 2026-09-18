<script setup lang="ts">
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import { useAppStore } from "@/stores/app";
import { useAuthStore } from "@/stores/auth";

const appStore = useAppStore();
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();

const menuRoutes = computed(() =>
  router
    .getRoutes()
    .filter((item) => item.meta?.title && !item.meta?.hidden && item.path !== "/")
    .sort((a, b) => a.path.localeCompare(b.path)),
);

async function initializeUser() {
  if (!authStore.userInfo && authStore.isLoggedIn) {
    try {
      await authStore.fetchMe();
    } catch {
      authStore.logout();
      await router.replace("/login");
    }
  }
}

async function handleLogout() {
  authStore.logout();
  await router.replace("/login");
}

onMounted(() => {
  void initializeUser();
});
</script>

<template>
  <div class="layout-shell">
    <aside class="layout-sidebar">
      <div class="layout-brand">
        <span class="layout-brand__name">{{ appStore.appTitle }}</span>
        <span class="layout-brand__desc">企业级模型治理平台</span>
      </div>

      <nav class="layout-menu">
        <RouterLink
          v-for="item in menuRoutes"
          :key="item.path"
          :to="item.path"
          class="layout-menu__item"
          :class="{ 'is-active': route.path === item.path }"
        >
          <span class="layout-menu__section">{{ item.meta.section }}</span>
          <span class="layout-menu__title">{{ item.meta.title }}</span>
        </RouterLink>
      </nav>
    </aside>

    <main class="layout-main">
      <header class="layout-header">
        <div class="layout-header__inner">
          <div>
            <div class="layout-header__title">{{ appStore.headerTitle }}</div>
            <div class="layout-header__subtitle">
              当前环境：{{ appStore.environment }} / 当前页面：{{ route.meta.title }}
            </div>
          </div>

          <div class="layout-user">
            <div class="layout-user__name">{{ authStore.displayName }}</div>
            <div class="layout-user__role">{{ authStore.userInfo?.roles?.join(" / ") ?? "未登录" }}</div>
            <button class="layout-user__logout" type="button" @click="handleLogout">退出登录</button>
          </div>
        </div>
      </header>

      <div class="layout-content">
        <RouterView />
      </div>
    </main>
  </div>
</template>
