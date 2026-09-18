<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "@/stores/auth";

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const loading = ref(false);
const errorMessage = ref("");
const form = reactive({
  username: "admin",
  password: "Admin@123456",
});

async function handleLogin() {
  loading.value = true;
  errorMessage.value = "";

  try {
    await authStore.login({
      username: form.username,
      password: form.password,
    });
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/dashboard";
    await router.replace(redirect);
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "登录失败，请检查账号密码。";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <section class="login-page">
    <div class="login-card">
      <div class="page-card__badge">认证与用户</div>
      <h1 class="login-card__title">登录 AI Gateway</h1>
      <p class="login-card__description">
        先把登录主链路跑通。当前默认演示账号已预填，后续可以继续接 RBAC、组织选择和刷新令牌。
      </p>

      <div class="login-tips">
        <span>演示账号：`admin`</span>
        <span>演示密码：`Admin@123456`</span>
      </div>

      <label class="login-field">
        <span>用户名 / 邮箱</span>
        <input v-model="form.username" type="text" autocomplete="username" />
      </label>

      <label class="login-field">
        <span>密码</span>
        <input v-model="form.password" type="password" autocomplete="current-password" />
      </label>

      <div v-if="errorMessage" class="login-error">
        {{ errorMessage }}
      </div>

      <button class="login-submit" type="button" :disabled="loading" @click="handleLogin">
        {{ loading ? "登录中..." : "立即登录" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 100%);
}

.login-card {
  width: 100%;
  max-width: 460px;
  padding: 32px;
  border-radius: 24px;
  background: #ffffff;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.12);
}

.login-card__title {
  margin: 0 0 12px;
  font-size: 30px;
}

.login-card__description {
  margin: 0 0 20px;
  color: #475569;
  line-height: 1.7;
}

.login-tips {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
  padding: 14px 16px;
  border-radius: 14px;
  background: #f8fafc;
  color: #334155;
  font-size: 14px;
}

.login-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}

.login-field input {
  width: 100%;
  padding: 12px 14px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  font-size: 14px;
}

.login-error {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 12px;
  background: #fee2e2;
  color: #b91c1c;
}

.login-submit {
  width: 100%;
  padding: 12px 16px;
  border: 0;
  border-radius: 12px;
  background: #1d4ed8;
  color: #eff6ff;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.login-submit:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
</style>
