import { ref } from "vue";

export type ToastType = "success" | "error" | "info";

export interface ToastMessage {
  id: number;
  type: ToastType;
  text: string;
}

export const activeToast = ref<ToastMessage | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;
let nextId = 0;

export function dismissToast() {
  if (timer) clearTimeout(timer);
  timer = undefined;
  activeToast.value = null;
}

export function showToast(type: ToastType, text: string) {
  if (timer) clearTimeout(timer);
  const id = ++nextId;
  activeToast.value = { id, type, text };
  timer = setTimeout(() => {
    if (activeToast.value?.id === id) dismissToast();
  }, 3000);
}
