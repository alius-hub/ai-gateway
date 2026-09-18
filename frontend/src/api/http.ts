import axios from "axios";

import { getAccessToken, removeAccessToken, removeUserCache } from "@/utils/auth";

export const http = axios.create({
  baseURL: import.meta.env.VITE_ADMIN_API_BASE_URL ?? "/api/admin/v1",
  timeout: 15000,
});

http.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use((response) => response.data);

http.interceptors.response.use(undefined, (error) => {
  if (error.response?.status === 401) {
    removeAccessToken();
    removeUserCache();
    if (window.location.pathname !== "/login") {
      const redirect = encodeURIComponent(window.location.pathname);
      window.location.href = `/login?redirect=${redirect}`;
    }
  }
  return Promise.reject(error);
});
