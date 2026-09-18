import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { fetchCurrentUser, login as loginRequest } from "@/api/auth";
import type { LoginPayload, UserInfo } from "@/types/auth";
import {
  getAccessToken,
  getUserCache,
  removeAccessToken,
  removeUserCache,
  setAccessToken,
  setUserCache,
} from "@/utils/auth";

function readCachedUser(): UserInfo | null {
  const raw = getUserCache();
  if (!raw) {
    return null;
  }

  try {
    return JSON.parse(raw) as UserInfo;
  } catch {
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const accessToken = ref(getAccessToken());
  const userInfo = ref<UserInfo | null>(readCachedUser());

  const isLoggedIn = computed(() => Boolean(accessToken.value));
  const displayName = computed(() => userInfo.value?.display_name ?? "未登录");

  async function login(payload: LoginPayload) {
    const response = await loginRequest(payload);
    accessToken.value = response.access_token;
    userInfo.value = response.user_info;
    setAccessToken(response.access_token);
    setUserCache(JSON.stringify(response.user_info));
    return response;
  }

  async function fetchMe() {
    if (!accessToken.value) {
      return null;
    }

    const user = await fetchCurrentUser();
    userInfo.value = user;
    setUserCache(JSON.stringify(user));
    return user;
  }

  function logout() {
    accessToken.value = "";
    userInfo.value = null;
    removeAccessToken();
    removeUserCache();
  }

  return {
    accessToken,
    userInfo,
    isLoggedIn,
    displayName,
    login,
    fetchMe,
    logout,
  };
});
