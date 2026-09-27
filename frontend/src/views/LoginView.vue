<script setup lang="ts">
import { reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import LanguageSwitcher from "@/LanguageSwitcher.vue";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import { showToast } from "@/utils/toast";

const authStore = useAuthStore();
const router = useRouter();
const route = useRoute();

const loading = ref(false);
const passwordVisible = ref(false);
const form = reactive({
  username: "",
  password: "",
});

async function handleLogin() {
  if (loading.value) return;

  loading.value = true;

  try {
    await authStore.login({
      username: form.username.trim(),
      password: form.password,
    });
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/dashboard";
    await router.replace(redirect);
    showToast("success", t("登录成功"));
  } catch (error) {
    showToast("error", t(error instanceof Error ? error.message : "登录失败，请检查账号密码。"));
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-showcase" :aria-label="t('AI Gateway 平台介绍')">
      <div class="showcase-top">
        <div class="brand">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none">
              <path d="M20 3 35 12v16L20 37 5 28V12L20 3Z" stroke="currentColor" stroke-width="2" />
              <path d="m5 12 15 9 15-9M20 21v16M12 16l8-5 8 5" stroke="currentColor" stroke-width="2" />
            </svg>
          </span>
          <span class="brand-copy">
            <strong>AI Gateway</strong>
            <small>MODEL OPERATIONS</small>
          </span>
        </div>
        <span class="showcase-label">CONTROL CENTER / 01</span>
      </div>

      <div class="showcase-content">
        <span class="showcase-eyebrow"><span class="eyebrow-line"></span> {{ t("统一接入 · 精细治理") }}</span>
        <h1>{{ t("让每一次模型调用") }}<br /><span>{{ t("清晰可控。") }}</span></h1>
        <p>{{ t("连接模型、管理流量、洞察用量。在同一个工作台中，掌握从接入到交付的每一步。") }}</p>

        <div class="flow-card" aria-hidden="true">
          <div class="flow-card__top">
            <span><span class="flow-card__signal"></span> MODEL REQUEST FLOW</span>
            <span>01 / 03</span>
          </div>
          <div class="flow-track">
            <div class="flow-node">
              <span class="flow-node__icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
                  <path d="M4 7h16M4 12h16M4 17h10" />
                </svg>
              </span>
              <span>{{ t("请求接入") }}</span>
            </div>
            <span class="flow-connector"></span>
            <div class="flow-node flow-node--active">
              <span class="flow-node__icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 3 20 7v10l-8 4-8-4V7l8-4ZM4 7l8 5 8-5M12 12v9" />
                </svg>
              </span>
              <span>{{ t("智能调度") }}</span>
            </div>
            <span class="flow-connector"></span>
            <div class="flow-node">
              <span class="flow-node__icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m5 12 4 4L19 6" />
                </svg>
              </span>
              <span>{{ t("结果交付") }}</span>
            </div>
          </div>
          <div class="flow-card__bottom">
            <span>ACCESS</span><span>ROUTING</span><span>DELIVERY</span>
          </div>
        </div>
      </div>

      <div class="showcase-bottom">
        <span>AI GATEWAY <span class="bottom-separator">/</span> PLATFORM CONSOLE</span>
        <span>{{ t("统一 · 稳定 · 可观测") }}</span>
      </div>
    </section>

    <section class="login-panel" aria-labelledby="login-title">
      <div class="login-panel__top">
        <div class="mobile-brand">
          <span class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 40 40" fill="none">
              <path d="M20 3 35 12v16L20 37 5 28V12L20 3Z" stroke="currentColor" stroke-width="2" />
              <path d="m5 12 15 9 15-9M20 21v16M12 16l8-5 8 5" stroke="currentColor" stroke-width="2" />
            </svg>
          </span>
          <strong>AI Gateway</strong>
        </div>
        <LanguageSwitcher />
      </div>

      <div class="login-panel__content">
        <div class="login-intro">
          <span class="login-intro__label"><span class="intro-dot"></span> {{ t("工作台登录") }}</span>
          <h2 id="login-title">{{ t("欢迎回来") }}</h2>
          <p>{{ t("登录账号，继续管理你的模型服务。") }}</p>
        </div>

        <form class="login-form" @submit.prevent="handleLogin">
          <label class="login-field" for="login-username">{{ t("用户名或邮箱") }}</label>
          <div class="input-wrap">
            <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
              <path d="M20 21v-2a6 6 0 0 0-6-6h-4a6 6 0 0 0-6 6v2M12 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z" />
            </svg>
            <input
              id="login-username"
              v-model="form.username"
              type="text"
              name="username"
              autocomplete="username"
              :placeholder="t('请输入用户名或邮箱')"
              required
            />
          </div>

          <label class="login-field" for="login-password">{{ t("密码") }}</label>
          <div class="input-wrap">
            <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">
              <rect x="4" y="10" width="16" height="11" rx="2" />
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
            </svg>
            <input
              id="login-password"
              v-model="form.password"
              :type="passwordVisible ? 'text' : 'password'"
              name="password"
              autocomplete="current-password"
              :placeholder="t('请输入密码')"
              required
            />
            <button
              class="password-toggle"
              type="button"
              :aria-label="t(passwordVisible ? '隐藏密码' : '显示密码')"
              :aria-pressed="passwordVisible"
              @click="passwordVisible = !passwordVisible"
            >
              <svg v-if="passwordVisible" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M3 3l18 18M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 5.2a10 10 0 0 1 2.1-.2c5.5 0 9 7 9 7a14 14 0 0 1-3.2 3.8M6.1 6.1C3.8 7.9 3 12 3 12s3.5 7 9 7a9.8 9.8 0 0 0 3.1-.5" />
              </svg>
              <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>

          <button class="login-submit" type="submit" :disabled="loading">
            <span>{{ t(loading ? "正在登录..." : "进入控制台") }}</span>
            <svg v-if="!loading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M4 12h16m-6-6 6 6-6 6" />
            </svg>
          </button>
        </form>

        <p class="login-help">{{ t("账号由平台管理员分配。如需开通或重置密码，请联系管理员。") }}</p>
      </div>
      <div class="login-panel__footer">
        <span>{{ t("AI Gateway 管理平台") }}</span>
        <span>{{ t("安全访问 · 统一治理") }}</span>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(480px, 0.95fr);
  min-height: 100vh;
  min-height: 100dvh;
}

.login-showcase {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 680px;
  padding: 40px clamp(32px, 5.2vw, 88px) 32px;
  background: radial-gradient(circle at 87% 55%, #1d4d58 0, transparent 38%),
    radial-gradient(circle at 9% 92%, #192f42 0, transparent 45%), #111927;
  color: #f2f7f9;
}

.login-showcase::before {
  position: absolute;
  inset: 0;
  background-image: linear-gradient(rgba(146, 216, 207, 0.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(146, 216, 207, 0.035) 1px, transparent 1px);
  background-size: 52px 52px;
  content: "";
  pointer-events: none;
}

.showcase-top,
.showcase-content,
.showcase-bottom {
  position: relative;
  z-index: 1;
}

.showcase-top,
.showcase-bottom,
.brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  justify-content: flex-start;
  gap: 13px;
}

.brand-mark {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  flex: none;
  border: 1px solid rgba(126, 232, 218, 0.5);
  border-radius: 13px;
  background: linear-gradient(145deg, #225d69, #163443);
  color: #7ee8da;
}

.brand-mark svg {
  width: 28px;
  height: 28px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.brand-copy strong {
  font-size: 18px;
  letter-spacing: -0.03em;
}

.brand-copy small,
.showcase-label,
.showcase-bottom,
.flow-card__top,
.flow-card__bottom {
  color: #8298a9;
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.14em;
}

.showcase-content {
  width: min(100%, 630px);
  margin: auto 0;
  padding: 62px 0;
}

.showcase-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  color: #8ce5d6;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.13em;
}

.eyebrow-line {
  width: 22px;
  height: 1px;
  background: currentColor;
}

.showcase-content h1 {
  margin: 26px 0 22px;
  font-size: clamp(42px, 4vw, 68px);
  font-weight: 650;
  letter-spacing: -0.065em;
  line-height: 1.18;
}

.showcase-content h1 span {
  color: #84e5d7;
}

.showcase-content > p {
  max-width: 440px;
  margin: 0;
  color: #9eafc0;
  font-size: 15px;
  line-height: 1.9;
}

.flow-card {
  max-width: 555px;
  margin-top: clamp(44px, 7vh, 96px);
  padding: 20px 25px 18px;
  border: 1px solid #395262;
  border-radius: 17px;
  background: rgba(27, 48, 63, 0.75);
  box-shadow: 0 24px 68px rgba(0, 0, 0, 0.15);
}

.flow-card__top,
.flow-card__bottom {
  display: flex;
  justify-content: space-between;
}

.flow-card__top > span:first-child {
  display: flex;
  align-items: center;
  gap: 9px;
  color: #b8cad2;
}

.flow-card__signal,
.intro-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #77dccb;
  box-shadow: 0 0 12px rgba(119, 220, 203, 0.55);
}

.flow-track {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 30px 3px 22px;
}

.flow-node {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: #a4b7c4;
  font-size: 11px;
}

.flow-node--active {
  color: #a5f2e6;
}

.flow-node__icon {
  display: grid;
  place-items: center;
  width: 47px;
  height: 47px;
  border: 1px solid #455c6a;
  border-radius: 13px;
  background: #263c4c;
}

.flow-node--active .flow-node__icon {
  border-color: #5ec8b8;
  background: #285a60;
  box-shadow: 0 0 25px rgba(69, 190, 175, 0.18);
}

.flow-node__icon svg {
  width: 22px;
  height: 22px;
}

.flow-connector {
  flex: 1;
  height: 1px;
  margin-bottom: 20px;
  background: linear-gradient(90deg, #496473, #6bd8c6, #496473);
}

.flow-card__bottom {
  padding-top: 15px;
  border-top: 1px solid #395262;
  font-size: 9px;
}

.showcase-bottom {
  gap: 16px;
}

.bottom-separator {
  margin: 0 6px;
  color: #6fd7c8;
}

.login-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 32px clamp(32px, 6vw, 105px);
  background: #f9fafb;
}

.login-panel__top {
  display: flex;
  align-items: center;
}

.login-panel__content {
  width: min(100%, 410px);
  margin: auto;
  padding: 55px 0;
}

.login-intro__label {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: #287b76;
  font-size: 12px;
  font-weight: 700;
}

.intro-dot {
  width: 6px;
  height: 6px;
  background: #3aa694;
}

.login-intro h2 {
  margin: 17px 0 9px;
  color: #172535;
  font-size: clamp(32px, 3vw, 42px);
  font-weight: 700;
  letter-spacing: -0.05em;
}

.login-intro p {
  margin: 0;
  color: #788798;
  font-size: 14px;
  line-height: 1.7;
}

.login-form {
  display: flex;
  flex-direction: column;
  margin-top: 43px;
}

.login-field {
  margin-bottom: 10px;
  color: #29394a;
  font-size: 13px;
  font-weight: 650;
}

.input-wrap {
  display: flex;
  align-items: center;
  height: 52px;
  margin-bottom: 25px;
  border: 1px solid #dbe2e9;
  border-radius: 11px;
  background: #fff;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

.input-wrap:focus-within {
  border-color: #369e93;
  box-shadow: 0 0 0 4px rgba(54, 158, 147, 0.11);
}

.input-icon {
  width: 19px;
  height: 19px;
  flex: none;
  margin-left: 16px;
  color: #8b9aa8;
}

.input-wrap input {
  width: 100%;
  min-width: 0;
  height: 100%;
  padding: 0 14px;
  border: 0;
  outline: 0;
  background: transparent;
  color: #1a2b3c;
  font: inherit;
  font-size: 14px;
}

.input-wrap input::placeholder {
  color: #a0adba;
}

.password-toggle {
  display: grid;
  place-items: center;
  width: 43px;
  height: 43px;
  flex: none;
  margin-right: 4px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #8797a6;
  cursor: pointer;
}

.password-toggle:hover {
  color: #277c75;
}

.password-toggle svg {
  width: 19px;
  height: 19px;
}

.login-submit {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  width: 100%;
  min-height: 53px;
  margin-top: 5px;
  border: 0;
  border-radius: 10px;
  background: #1a665f;
  color: #fff;
  font: inherit;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: background 160ms ease, transform 160ms ease;
}

.login-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  background: #12564f;
}

.login-submit:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.login-submit svg {
  width: 18px;
  height: 18px;
}

.password-toggle:focus-visible,
.login-submit:focus-visible {
  outline: 2px solid #318f84;
  outline-offset: 3px;
}

.login-help {
  margin: 23px 0 0;
  color: #8996a4;
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
}

.login-panel__footer {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  color: #98a5b2;
  font-size: 11px;
}

.mobile-brand {
  display: none;
}

@media (max-width: 1050px) {
  .login-page {
    grid-template-columns: minmax(0, 1fr) minmax(410px, 0.9fr);
  }

  .login-showcase {
    padding-right: 38px;
    padding-left: 38px;
  }

  .showcase-label {
    display: none;
  }

  .login-panel {
    padding-right: 42px;
    padding-left: 42px;
  }
}

@media (max-width: 780px) {
  .login-page {
    display: block;
  }

  .login-showcase {
    display: none;
  }

  .login-panel {
    min-height: 100vh;
    min-height: 100dvh;
    padding: 25px clamp(24px, 7vw, 52px);
  }

  .mobile-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: #172535;
    font-size: 17px;
    letter-spacing: -0.03em;
  }

  .mobile-brand .brand-mark {
    width: 37px;
    height: 37px;
  }

  .mobile-brand .brand-mark svg {
    width: 23px;
    height: 23px;
  }
}

@media (max-width: 420px) {
  .login-panel__content {
    padding: 52px 0;
  }

  .login-form {
    margin-top: 35px;
  }

  .login-panel__footer span:last-child {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .input-wrap,
  .login-submit {
    transition: none;
  }
}
</style>
