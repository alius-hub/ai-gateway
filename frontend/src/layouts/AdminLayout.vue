<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";

import LanguageSwitcher from "@/LanguageSwitcher.vue";
import { t } from "@/i18n";
import { navigation, type NavigationIcon } from "@/router/navigation";
import { useAppStore } from "@/stores/app";
import { useAuthStore } from "@/stores/auth";

const appStore = useAppStore();
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const roleNames: Record<string, string> = {
  platform_admin: "平台管理员",
  org_admin: "组织管理员",
  project_admin: "项目管理员",
  member: "成员",
  readonly: "只读成员",
};
const userRole = computed(() =>
  authStore.userInfo?.roles?.map((role) => t(roleNames[role] ?? role)).join(" / ") || t("未设置角色"),
);
const breadcrumb = computed(() => {
  if (route.path === "/dashboard") return { group: "", page: t("总览") };

  const group = navigation.find((entry) =>
    entry.items.some((item) => item.path === route.path),
  );
  const item = group?.items.find((entry) => entry.path === route.path);

  return {
    group: group ? t(group.label) : "",
    page: t(item?.label ?? String(route.meta.title ?? "当前页面")),
  };
});

const icons: Record<NavigationIcon, string[]> = {
  overview: ["M3 3v18h18", "M7 15l4-4 3 2 4-6"],
  models: ["M12 2l9 5-9 5-9-5 9-5Z", "M3 12l9 5 9-5", "M3 17l9 5 9-5"],
  people: ["M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M22 21v-2a4 4 0 0 0-3-3.87", "M16 3.13a4 4 0 0 1 0 7.75"],
  keys: ["M15 7a5 5 0 1 1-2 9.58L9 21H5v-4H2v-3l6.42-6.42A5 5 0 0 1 15 7Z", "M16 9h.01"],
  security: ["M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z", "M9 12l2 2 4-4"],
  analytics: ["M3 3v18h18", "M7 16v-4", "M12 16V7", "M17 16v-7"],
  logs: ["M8 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V8l-5-5H8Z", "M15 3v6h6", "M7 13h10", "M7 17h10"],
  alerts: ["M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z", "M10 21h4"],
  mcp: ["M12 3v6", "M5 9h14", "M5 9v6", "M19 9v6", "M3 15h4v5H3z", "M10 15h4v5h-4z", "M17 15h4v5h-4z"],
  settings: ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-1.86 1.86-.06-.06A1.7 1.7 0 0 0 16 18.4a1.7 1.7 0 0 0-1 1.56V21h-6v-1.04a1.7 1.7 0 0 0-1-1.56 1.7 1.7 0 0 0-1.88.34l-.06.06-1.86-1.86.06-.06A1.7 1.7 0 0 0 4.6 15 1.7 1.7 0 0 0 3.04 14H2v-4h1.04A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.88L4.2 7.06 6.06 5.2l.06.06A1.7 1.7 0 0 0 8 5.6a1.7 1.7 0 0 0 1-1.56V3h6v1.04a1.7 1.7 0 0 0 1 1.56 1.7 1.7 0 0 0 1.88-.34l.06-.06 1.86 1.86-.06.06A1.7 1.7 0 0 0 19.4 9a1.7 1.7 0 0 0 1.56 1H22v4h-1.04A1.7 1.7 0 0 0 19.4 15Z"],
};

function groupForPath(path: string) {
  return navigation.find((group) => group.items.some((item) => item.path === path))?.id ?? "overview";
}

const expandedGroup = ref<NavigationIcon | null>(groupForPath(route.path));
const sidebarOpen = ref(false);
const sidebarCollapsed = ref(false);
const accountMenuOpen = ref(false);
const accountMenuRoot = ref<HTMLElement | null>(null);
const accountTrigger = ref<HTMLButtonElement | null>(null);
const logoutButton = ref<HTMLButtonElement | null>(null);

watch(
  () => route.path,
  (path) => {
    if (!sidebarCollapsed.value) expandedGroup.value = groupForPath(path);
    sidebarOpen.value = false;
    accountMenuOpen.value = false;
  },
);

function toggleGroup(id: NavigationIcon) {
  if (sidebarCollapsed.value) {
    sidebarCollapsed.value = false;
    expandedGroup.value = id;
    return;
  }
  expandedGroup.value = expandedGroup.value === id ? null : id;
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value;
  expandedGroup.value = sidebarCollapsed.value ? null : groupForPath(route.path);
  accountMenuOpen.value = false;
}

function closeOnEscape(event: KeyboardEvent) {
  if (event.key !== "Escape") return;
  if (accountMenuOpen.value) {
    accountMenuOpen.value = false;
    accountTrigger.value?.focus();
  } else {
    sidebarOpen.value = false;
  }
}

function closeAccountMenuOutside(event: PointerEvent) {
  if (accountMenuOpen.value && !accountMenuRoot.value?.contains(event.target as Node)) {
    accountMenuOpen.value = false;
  }
}

async function toggleAccountMenu() {
  accountMenuOpen.value = !accountMenuOpen.value;
  if (accountMenuOpen.value) {
    await nextTick();
    logoutButton.value?.focus();
  }
}

onMounted(() => {
  window.addEventListener("keydown", closeOnEscape);
  window.addEventListener("pointerdown", closeAccountMenuOutside);
});
onUnmounted(() => {
  window.removeEventListener("keydown", closeOnEscape);
  window.removeEventListener("pointerdown", closeAccountMenuOutside);
});

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
  accountMenuOpen.value = false;
  authStore.logout();
  await router.replace("/login");
}

onMounted(() => {
  void initializeUser();
});
</script>

<template>
  <div class="layout-shell" :class="{ 'is-collapsed': sidebarCollapsed }">
    <button
      v-if="sidebarOpen"
      class="sidebar-scrim"
      type="button"
      :aria-label="t('关闭导航菜单')"
      @click="sidebarOpen = false"
    ></button>
    <aside id="primary-sidebar" class="layout-sidebar" :class="{ 'is-open': sidebarOpen }">
      <div class="layout-brand">
        <span class="layout-brand__mark" aria-hidden="true">
          <svg viewBox="0 0 40 40" fill="none">
            <path d="M20 3 35 12v16L20 37 5 28V12L20 3Z" stroke="currentColor" stroke-width="2" />
            <path d="m5 12 15 9 15-9M20 21v16M12 16l8-5 8 5" stroke="currentColor" stroke-width="2" />
          </svg>
        </span>
        <span class="layout-brand__copy">
          <span class="layout-brand__name">{{ appStore.appTitle }}</span>
          <span class="layout-brand__desc">MODEL OPERATIONS</span>
        </span>
        <button
          class="sidebar-collapse"
          type="button"
          :aria-label="t(sidebarCollapsed ? '展开侧边栏' : '收起侧边栏')"
          :title="t(sidebarCollapsed ? '展开侧边栏' : '收起侧边栏')"
          aria-controls="primary-sidebar"
          :aria-expanded="!sidebarCollapsed"
          @click="toggleSidebar"
        >
          <svg :class="{ 'is-reversed': sidebarCollapsed }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M4 5h16M4 12h16M4 19h16M10 9l-3 3 3 3" />
          </svg>
        </button>
        <button class="sidebar-close" type="button" :aria-label="t('关闭导航菜单')" @click="sidebarOpen = false">×</button>
      </div>

      <nav class="layout-menu" :aria-label="t('主导航')">
        <div class="layout-menu__caption">NAVIGATION <span>{{ t("导航目录") }}</span></div>
        <div v-for="group in navigation" :key="group.id" class="layout-menu__group">
          <RouterLink
            v-if="group.items.length === 1"
            :to="group.items[0].path"
            class="layout-menu__heading"
            :class="{ 'is-active': route.path === group.items[0].path }"
            :aria-current="route.path === group.items[0].path ? 'page' : undefined"
            :aria-label="sidebarCollapsed ? t(group.label) : undefined"
            :title="sidebarCollapsed ? t(group.label) : undefined"
            @click="sidebarOpen = false"
          >
            <svg class="layout-menu__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path v-for="(path, index) in icons[group.id]" :key="index" :d="path" />
            </svg>
            <span>{{ t(group.label) }}</span>
            <span v-if="group.items[0].planned" class="layout-menu__planned layout-menu__planned--heading">{{ t("规划中") }}</span>
          </RouterLink>
          <template v-else>
            <button
              class="layout-menu__heading"
              :class="{ 'has-active': group.items.some((item) => item.path === route.path) }"
              type="button"
              :aria-expanded="expandedGroup === group.id"
              :aria-controls="`menu-${group.id}`"
              :aria-label="sidebarCollapsed ? t(group.label) : undefined"
              :title="sidebarCollapsed ? t(group.label) : undefined"
              @click="toggleGroup(group.id)"
            >
              <svg class="layout-menu__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path v-for="(path, index) in icons[group.id]" :key="index" :d="path" />
              </svg>
              <span>{{ t(group.label) }}</span>
              <svg class="layout-menu__chevron" :class="{ 'is-expanded': expandedGroup === group.id }" viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
            <div v-show="expandedGroup === group.id" :id="`menu-${group.id}`" class="layout-menu__children">
              <RouterLink
                v-for="item in group.items"
                :key="item.path"
                :to="item.path"
                class="layout-menu__item"
                :class="{ 'is-active': route.path === item.path }"
                :aria-current="route.path === item.path ? 'page' : undefined"
                @click="sidebarOpen = false"
              >
                <span class="layout-menu__item-label">{{ t(item.label) }}</span>
                <span v-if="item.planned" class="layout-menu__planned">{{ t("规划中") }}</span>
              </RouterLink>
            </div>
          </template>
        </div>
      </nav>
      <div ref="accountMenuRoot" class="sidebar-footer">
        <div class="sidebar-footer__meta">
          <span class="sidebar-footer__dot"></span>
          <span>AI Gateway</span>
          <span class="sidebar-footer__version">{{ appStore.environment.toUpperCase() }}</span>
        </div>
        <div v-show="accountMenuOpen" id="account-actions" class="sidebar-account-menu">
          <div class="sidebar-account-menu__label">{{ t("当前账号") }}</div>
          <div class="sidebar-account-menu__name">{{ authStore.displayName }}</div>
          <button ref="logoutButton" class="sidebar-account-menu__logout" type="button" @click="handleLogout">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M16 17l5-5-5-5M21 12H9" />
            </svg>
            {{ t("退出登录") }}
          </button>
        </div>
        <button
          ref="accountTrigger"
          class="sidebar-user"
          type="button"
          :aria-label="t('账户菜单')"
          aria-controls="account-actions"
          :aria-expanded="accountMenuOpen"
          @click="toggleAccountMenu"
        >
          <span class="sidebar-user__avatar" aria-hidden="true">
            {{ authStore.displayName.slice(0, 1).toUpperCase() }}
          </span>
          <span class="sidebar-user__info">
            <span class="sidebar-user__name" :title="t(authStore.displayName)">{{ t(authStore.displayName) }}</span>
            <span class="sidebar-user__role" :title="userRole">{{ userRole }}</span>
          </span>
          <span class="sidebar-user__chevron" :class="{ 'is-open': accountMenuOpen }" aria-hidden="true">
            <svg viewBox="0 0 20 20" fill="none">
              <path d="m6 8 4 4 4-4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </span>
        </button>
      </div>
    </aside>

    <main class="layout-main">
      <header class="layout-header">
        <div class="layout-header__inner">
          <button
            class="sidebar-toggle"
            type="button"
            :aria-label="t('打开导航菜单')"
            aria-controls="primary-sidebar"
            :aria-expanded="sidebarOpen"
            @click="sidebarOpen = true"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <nav class="layout-breadcrumb" :aria-label="t('面包屑导航')">
            <ol>
              <li>
                <RouterLink v-if="route.path !== '/dashboard'" to="/dashboard" class="layout-breadcrumb__home">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10Z" />
                  </svg>
                  {{ t("总览") }}
                </RouterLink>
                <span v-else class="layout-breadcrumb__current" aria-current="page">{{ t("总览") }}</span>
              </li>
              <li v-if="breadcrumb.group" class="layout-breadcrumb__part">
                <span class="layout-breadcrumb__separator" aria-hidden="true">/</span>
                <span>{{ breadcrumb.group }}</span>
              </li>
              <li v-if="route.path !== '/dashboard'" class="layout-breadcrumb__part">
                <span class="layout-breadcrumb__separator" aria-hidden="true">/</span>
                <span class="layout-breadcrumb__current" aria-current="page">{{ breadcrumb.page }}</span>
              </li>
            </ol>
          </nav>
          <LanguageSwitcher />
        </div>
      </header>

      <div class="layout-content">
        <RouterView />
      </div>
    </main>
  </div>
</template>
