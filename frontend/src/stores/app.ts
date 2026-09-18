import { computed, ref } from "vue";
import { defineStore } from "pinia";

export const useAppStore = defineStore("app", () => {
  const appTitle = ref("AI Gateway");
  const environment = ref(import.meta.env.VITE_APP_ENV ?? "dev");

  const headerTitle = computed(() => `${appTitle.value} 控制台`);

  return {
    appTitle,
    environment,
    headerTitle,
  };
});
