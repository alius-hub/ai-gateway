import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devProxyTarget = env.VITE_DEV_PROXY_TARGET || "http://localhost:8001";

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: devProxyTarget,
          changeOrigin: true,
        },
        "/v1": {
          target: devProxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
