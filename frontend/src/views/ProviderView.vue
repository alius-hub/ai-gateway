<script setup lang="ts">
import { ref, watch } from "vue";

import AppPagination from "@/AppPagination.vue";
import AppSelect from "@/AppSelect.vue";
import {
  createProtocol, createProvider, createSecret, listProtocols, listProviders, listSecrets,
  setProviderStatus, updateProtocol, updateProvider, updateSecret,
  type ProviderPayload, type ProviderProtocol, type ProviderSecret,
} from "@/api/providers";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import type { ProviderItem } from "@/types/resource";
import { showToast } from "@/utils/toast";

const auth = useAuthStore();
const records = ref<ProviderItem[]>([]);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const keyword = ref("");
const loading = ref(false);
const busy = ref(false);
const editing = ref<ProviderItem | null>(null);
const formOpen = ref(false);
const confirmTarget = ref<ProviderItem | null>(null);
const connectionTarget = ref<ProviderItem | null>(null);
const protocols = ref<ProviderProtocol[]>([]);
const secrets = ref<ProviderSecret[]>([]);
const connectionBusy = ref(false);
const protocolEditing = ref<ProviderProtocol | null>(null);
const protocolForm = ref({ code: "", protocol_type: "openai_compatible", base_url: "" });
const secretForm = ref({ name: "", api_key: "" });
const rotating = ref<ProviderSecret | null>(null);
const pendingStatus = ref<{ kind: "protocol" | "secret"; id: number; status: number } | null>(null);
const form = ref<ProviderPayload>({ name: "", code: "", provider_type: "openai_compatible", base_url: "", api_key: "" });
const extraProtocols = ref<{ code: string; protocol_type: string; base_url: string }[]>([]);
const newSecrets = ref<{ name: string; api_key: string }[]>([]);
const initialStatus = ref(1);
let requestId = 0;
let connectionRequestId = 0;
const isAdmin = () => auth.userInfo?.roles.includes("platform_admin") ?? false;

function errorMessage(reason: unknown) {
  const detail = (reason as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || (reason instanceof Error ? reason.message : "操作失败，请重试");
}

async function load() {
  const id = ++requestId;
  loading.value = true;
  records.value = [];
  try {
    const result = await listProviders({ page: page.value, page_size: pageSize.value, keyword: keyword.value.trim() });
    if (id !== requestId) return;
    records.value = result.items;
    total.value = result.total;
  } catch (reason) {
    if (id === requestId) showToast("error", t(errorMessage(reason)));
  } finally {
    if (id === requestId) loading.value = false;
  }
}

function search() {
  if (page.value === 1) void load();
  else page.value = 1;
}

function openForm(item: ProviderItem | null = null) {
  editing.value = item;
  form.value = {
    name: item?.name ?? "", code: item?.code ?? "",
    provider_type: item?.provider_type ?? "openai_compatible",
    base_url: item?.base_url ?? "", api_key: "",
  };
  extraProtocols.value = [];
  newSecrets.value = [];
  initialStatus.value = 1;
  formOpen.value = true;
}

async function save() {
  if (busy.value) return;
  busy.value = true;
  try {
    const payload = { ...form.value };
    if (!payload.api_key?.trim()) delete payload.api_key;
    if (editing.value) await updateProvider(editing.value.id, { name: payload.name, code: payload.code });
    else await createProvider({
      ...payload,
      additional_protocols: extraProtocols.value.map((item) => ({ ...item })),
      secrets: newSecrets.value.map((item) => ({ ...item })),
      status: initialStatus.value,
    });
    formOpen.value = false;
    showToast("success", t(editing.value ? "已保存更改" : "创建成功"));
    await load();
  } catch (reason) {
    showToast("error", t(errorMessage(reason)));
  } finally {
    busy.value = false;
  }
}

async function refreshConnections() {
  const target = connectionTarget.value;
  if (!target) return;
  const id = ++connectionRequestId;
  try {
    const [nextProtocols, nextSecrets] = await Promise.all([
      listProtocols(target.id), isAdmin() ? listSecrets(target.id) : Promise.resolve([]),
    ]);
    if (id !== connectionRequestId) return;
    protocols.value = nextProtocols;
    secrets.value = nextSecrets;
  } catch (reason) {
    if (id === connectionRequestId) showToast("error", t(errorMessage(reason)));
  }
}

function openConnections(item: ProviderItem) {
  connectionTarget.value = item;
  protocols.value = [];
  secrets.value = [];
  protocolEditing.value = null;
  protocolForm.value = { code: "", protocol_type: "openai_compatible", base_url: "" };
  secretForm.value = { name: "", api_key: "" };
  void refreshConnections();
}

function closeConnections() {
  ++connectionRequestId;
  connectionTarget.value = null;
  rotating.value = null;
}

async function saveProtocol() {
  if (!connectionTarget.value || connectionBusy.value) return;
  connectionBusy.value = true;
  try {
    if (protocolEditing.value) {
      await updateProtocol(connectionTarget.value.id, protocolEditing.value.id, {
        protocol_type: protocolForm.value.protocol_type, base_url: protocolForm.value.base_url,
      });
    } else await createProtocol(connectionTarget.value.id, protocolForm.value);
    protocolEditing.value = null;
    protocolForm.value = { code: "", protocol_type: "openai_compatible", base_url: "" };
    showToast("success", t("已保存更改"));
    await refreshConnections();
    await load();
  } catch (reason) {
    showToast("error", t(errorMessage(reason)));
  } finally {
    connectionBusy.value = false;
  }
}

async function saveSecret() {
  if (!connectionTarget.value || connectionBusy.value) return;
  connectionBusy.value = true;
  try {
    if (rotating.value) await updateSecret(connectionTarget.value.id, rotating.value.id, { api_key: secretForm.value.api_key });
    else await createSecret(connectionTarget.value.id, secretForm.value.name, secretForm.value.api_key);
    rotating.value = null;
    secretForm.value = { name: "", api_key: "" };
    showToast("success", t("已保存更改"));
    await refreshConnections();
    await load();
  } catch (reason) {
    showToast("error", t(errorMessage(reason)));
  } finally {
    connectionBusy.value = false;
  }
}

async function confirmConnectionStatus() {
  const target = connectionTarget.value;
  const pending = pendingStatus.value;
  if (!target || !pending || connectionBusy.value) return;
  connectionBusy.value = true;
  try {
    if (pending.kind === "protocol") await updateProtocol(target.id, pending.id, { status: pending.status });
    else await updateSecret(target.id, pending.id, { status: pending.status });
    pendingStatus.value = null;
    showToast("success", t("状态已更新"));
    await refreshConnections();
  } catch (reason) {
    showToast("error", t(errorMessage(reason)));
  } finally {
    connectionBusy.value = false;
  }
}

async function confirmStatus() {
  if (!confirmTarget.value || busy.value) return;
  busy.value = true;
  try {
    await setProviderStatus(confirmTarget.value.id, confirmTarget.value.status === 1 ? 0 : 1);
    confirmTarget.value = null;
    showToast("success", t("状态已更新"));
    await load();
  } catch (reason) {
    showToast("error", t(errorMessage(reason)));
  } finally {
    busy.value = false;
  }
}

watch([page, pageSize], () => void load(), { immediate: true });
</script>

<template>
  <section class="page-stack provider-page">
    <header class="page-card provider-hero">
      <div><h1>{{ t("供应商管理") }}</h1><p>{{ t("维护模型接入地址、认证信息与启用状态。") }}</p></div>
      <button v-if="isAdmin()" class="page-action" type="button" @click="openForm()">{{ t("新建供应商") }}</button>
    </header>
    <div class="page-card provider-card">
      <div class="provider-toolbar">
        <div><h2>{{ t("供应商列表") }}</h2><p>{{ t("当前共 {count} 条记录", { count: total }) }}</p></div>
        <form class="provider-search" @submit.prevent="search">
          <input v-model="keyword" :aria-label="t('搜索供应商')" :placeholder="t('按名称或编码搜索')" />
          <button type="submit" :disabled="loading">{{ t("查询") }}</button>
          <button type="button" :disabled="loading" @click="load">{{ t("刷新") }}</button>
        </form>
      </div>
      <div class="resource-table-scroll">
        <table class="resource-table">
          <thead><tr><th>ID</th><th>{{ t("名称") }}</th><th>{{ t("编码") }}</th><th>{{ t("默认协议") }}</th><th>{{ t("默认地址") }}</th><th>{{ t("密钥数") }}</th><th>{{ t("协议数") }}</th><th>{{ t("状态") }}</th><th>{{ t("操作") }}</th></tr></thead>
          <tbody>
            <tr v-for="item in records" :key="item.id">
              <td>{{ item.id }}</td><td>{{ item.name }}</td><td>{{ item.code }}</td><td>{{ item.provider_type }}</td>
              <td :title="item.base_url">{{ item.base_url || "-" }}</td>
              <td>{{ item.secret_count ?? 0 }}</td><td>{{ item.protocol_count ?? 0 }}</td>
              <td><span class="provider-status" :class="{ 'is-off': item.status !== 1 }">{{ t(item.status === 1 ? "启用" : "停用") }}</span></td>
              <td><div class="provider-actions">
                <button type="button" @click="openConnections(item)">{{ t("连接配置") }}</button>
                <template v-if="isAdmin()">
                <button type="button" :disabled="busy" @click="openForm(item)">{{ t("编辑") }}</button>
                <button type="button" :class="{ 'is-danger': item.status === 1 }" :disabled="busy" @click="confirmTarget = item">{{ t(item.status === 1 ? "停用" : "启用") }}</button>
                </template>
              </div></td>
            </tr>
            <tr v-if="!records.length"><td colspan="9" class="provider-empty">{{ t(loading ? "正在加载数据..." : "暂无匹配记录") }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination v-if="total" v-model="page" v-model:page-size="pageSize" :total="total" :disabled="loading" />
    </div>
    <div v-if="formOpen" class="app-modal-overlay" @click.self="!busy && (formOpen = false)">
      <form class="app-modal-panel provider-dialog" :class="{ 'provider-dialog--wide': !editing }" role="dialog" aria-modal="true" :aria-label="t(editing ? '编辑供应商' : '新建供应商')" @submit.prevent="save">
        <header><h2>{{ t(editing ? "编辑供应商" : "新建供应商") }}</h2><button type="button" :disabled="busy" aria-label="关闭" @click="formOpen = false">×</button></header>
        <div class="provider-fields">
          <label>{{ t("名称") }} *<input v-model.trim="form.name" required maxlength="128" /></label>
          <label>{{ t("编码") }} *<input v-model.trim="form.code" required maxlength="64" pattern="[a-z0-9][a-z0-9_-]*" /></label>
          <template v-if="!editing">
            <label>{{ t("状态") }}<AppSelect :model-value="initialStatus" :options="[{ label: t('启用'), value: 1 }, { label: t('停用'), value: 0 }]" :aria-label="t('状态')" @update:model-value="initialStatus = Number($event)" /></label>
            <div class="provider-form-group">
              <h3>{{ t("协议与地址") }}</h3>
              <div class="provider-form-row">
                <span class="provider-form-label">{{ t("默认协议") }} (default)</span>
                <label>{{ t("协议类型") }} *<input v-model.trim="form.provider_type" required maxlength="64" /></label>
                <label>{{ t("基础地址") }} *<input v-model.trim="form.base_url" type="url" required maxlength="255" placeholder="https://api.example.com/v1" /></label>
              </div>
              <div v-for="(protocol, index) in extraProtocols" :key="index" class="provider-form-row">
                <label>{{ t("协议编码") }} *<input v-model.trim="protocol.code" required maxlength="64" pattern="[a-z0-9][a-z0-9_-]*" placeholder="protocol-code" /></label>
                <label>{{ t("协议类型") }} *<input v-model.trim="protocol.protocol_type" required maxlength="64" placeholder="openai_compatible" /></label>
                <label>{{ t("基础地址") }} *<input v-model.trim="protocol.base_url" type="url" required maxlength="255" placeholder="https://api.example.com/v1" /></label>
                <button type="button" :disabled="busy" @click="extraProtocols.splice(index, 1)">{{ t("移除") }}</button>
              </div>
              <button type="button" :disabled="busy" @click="extraProtocols.push({ code: '', protocol_type: 'openai_compatible', base_url: '' })">{{ t("添加协议") }}</button>
            </div>
            <div class="provider-form-group">
              <h3>{{ t("上游密钥") }}</h3>
              <div class="provider-form-row">
                <span class="provider-form-label">{{ t("默认密钥") }} (default)</span>
                <label>{{ t("API Key（可选）") }}<input v-model="form.api_key" type="password" autocomplete="new-password" maxlength="4096" /></label>
              </div>
              <div v-for="(secret, index) in newSecrets" :key="index" class="provider-form-row">
                <label>{{ t("密钥名称") }} *<input v-model.trim="secret.name" required maxlength="128" /></label>
                <label>{{ t("API Key") }} *<input v-model="secret.api_key" type="password" autocomplete="new-password" required maxlength="4096" /></label>
                <button type="button" :disabled="busy" @click="newSecrets.splice(index, 1)">{{ t("移除") }}</button>
              </div>
              <button type="button" :disabled="busy" @click="newSecrets.push({ name: '', api_key: '' })">{{ t("添加密钥") }}</button>
            </div>
          </template>
          <p>{{ t("配置 Key 需先设置后端加密密钥；创建后可在连接配置中继续管理。") }}</p>
        </div>
        <footer><button type="button" :disabled="busy" @click="formOpen = false">{{ t("取消") }}</button><button type="submit" :disabled="busy">{{ t(busy ? "保存中..." : "保存") }}</button></footer>
      </form>
    </div>
    <div v-if="connectionTarget" class="app-modal-overlay" @click.self="!connectionBusy && closeConnections()">
      <div class="app-modal-panel provider-dialog provider-dialog--wide" role="dialog" aria-modal="true" :aria-label="t('连接配置')">
        <header><h2>{{ connectionTarget.name }} · {{ t("连接配置") }}</h2><button type="button" aria-label="关闭" :disabled="connectionBusy" @click="closeConnections">×</button></header>
        <section class="provider-section">
          <h3>{{ t("协议与地址") }}</h3>
          <div v-for="item in protocols" :key="item.id" class="provider-connection">
            <div><strong>{{ item.code }} · {{ item.protocol_type }}</strong><small>{{ item.base_url }}</small></div>
            <span>{{ t(item.status === 1 ? "启用" : "停用") }}</span>
            <button v-if="isAdmin()" type="button" @click="protocolEditing = item; protocolForm = { code: item.code, protocol_type: item.protocol_type, base_url: item.base_url }">{{ t("编辑") }}</button>
            <button v-if="isAdmin()" type="button" @click="pendingStatus = { kind: 'protocol', id: item.id, status: item.status === 1 ? 0 : 1 }">{{ t(item.status === 1 ? "停用" : "启用") }}</button>
          </div>
          <form v-if="isAdmin()" class="provider-inline-form" @submit.prevent="saveProtocol">
            <input v-if="!protocolEditing" v-model.trim="protocolForm.code" :aria-label="t('协议编码')" placeholder="protocol-code" required pattern="[a-z0-9][a-z0-9_-]*" />
            <input v-model.trim="protocolForm.protocol_type" :aria-label="t('协议类型')" placeholder="openai_compatible" required />
            <input v-model.trim="protocolForm.base_url" :aria-label="t('基础地址')" placeholder="https://api.example.com/v1" type="url" required />
            <button type="submit" :disabled="connectionBusy">{{ t(protocolEditing ? "保存协议" : "添加协议") }}</button>
            <button v-if="protocolEditing" type="button" @click="protocolEditing = null; protocolForm = { code: '', protocol_type: 'openai_compatible', base_url: '' }">{{ t("取消") }}</button>
          </form>
        </section>
        <section v-if="isAdmin()" class="provider-section">
          <h3>{{ t("上游密钥") }}</h3>
          <p>{{ t("密钥只显示名称和状态，明文不会返回页面。") }}</p>
          <div v-for="item in secrets" :key="item.id" class="provider-connection">
            <strong>{{ item.name }}</strong><span>{{ t(item.status === 1 ? "启用" : "停用") }}</span>
            <button type="button" @click="rotating = item; secretForm = { name: item.name, api_key: '' }">{{ t("轮换") }}</button>
            <button type="button" @click="pendingStatus = { kind: 'secret', id: item.id, status: item.status === 1 ? 0 : 1 }">{{ t(item.status === 1 ? "停用" : "启用") }}</button>
          </div>
          <form class="provider-inline-form" @submit.prevent="saveSecret">
            <input v-if="!rotating" v-model.trim="secretForm.name" :aria-label="t('密钥名称')" :placeholder="t('密钥名称')" required maxlength="128" />
            <input v-model="secretForm.api_key" :aria-label="t('API Key')" type="password" autocomplete="new-password" required :placeholder="t('API Key')" />
            <button type="submit" :disabled="connectionBusy">{{ t(rotating ? "确认轮换" : "添加密钥") }}</button>
            <button v-if="rotating" type="button" @click="rotating = null; secretForm = { name: '', api_key: '' }">{{ t("取消") }}</button>
          </form>
        </section>
      </div>
    </div>
    <div v-if="pendingStatus" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!connectionBusy && (pendingStatus = null)">
      <div class="app-modal-panel provider-dialog" role="alertdialog" aria-modal="true" :aria-label="t('确认操作')">
        <header><h2>{{ t("确认操作") }}</h2></header>
        <p class="provider-confirm">{{ t(`确定${pendingStatus.status === 0 ? "停用" : "启用"}此配置吗？`) }}</p>
        <footer><button type="button" :disabled="connectionBusy" @click="pendingStatus = null">{{ t("取消") }}</button><button type="button" :disabled="connectionBusy" @click="confirmConnectionStatus">{{ t("确认") }}</button></footer>
      </div>
    </div>
    <div v-if="confirmTarget" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!busy && (confirmTarget = null)">
      <div class="app-modal-panel provider-dialog" role="alertdialog" aria-modal="true" :aria-label="t('确认操作')">
        <header><h2>{{ t("确认操作") }}</h2><button type="button" :disabled="busy" aria-label="关闭" @click="confirmTarget = null">×</button></header>
        <p class="provider-confirm">{{ t(`确定${confirmTarget.status === 1 ? "停用" : "启用"} ${confirmTarget.name} 吗？`) }}</p>
        <footer><button type="button" :disabled="busy" @click="confirmTarget = null">{{ t("取消") }}</button><button type="button" :class="{ 'provider-confirm-danger': confirmTarget.status === 1 }" :disabled="busy" @click="confirmStatus">{{ t("确认") }}</button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.provider-hero { display:flex; justify-content:space-between; align-items:center; gap:16px; }
.provider-hero h1 { margin:0 0 8px; font-size:23px; color:#172f3a; }
.provider-hero p,.provider-toolbar p { margin:0; color:#8a9ca8; font-size:12px; }
.provider-card { padding:0; overflow:hidden; }
.provider-toolbar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; padding:22px 24px; }
.provider-toolbar h2 { margin:0 0 6px; font-size:16px; }
.provider-search,.provider-actions { display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.provider-page input { min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; background:#fff; color:#29414d; font:inherit; font-size:12px; outline:none; }
.provider-page input:focus { border-color:#42aa98; box-shadow:0 0 0 3px #e2f5ee; }
.provider-page button:not(.page-action) { min-height:34px; padding:6px 12px; border:1px solid #d6e5e3; border-radius:9px; background:#f4faf8; color:#217c70; cursor:pointer; }
.provider-page .provider-actions button { min-height:34px; padding:4px 6px; border:0; background:transparent; color:#217c70; font:inherit; font-size:12px; }
.provider-page .provider-actions button:hover:not(:disabled) { text-decoration:underline; }
.provider-page .provider-actions button.is-danger { color:#d32f2f; font-weight:600; }
.provider-page .provider-actions button.is-danger:hover:not(:disabled) { color:#b71c1c; }
.provider-page button.provider-confirm-danger:not(.page-action) { border-color:#d32f2f; background:#d32f2f; color:#fff; }
.provider-page button.provider-confirm-danger:hover:not(:disabled) { border-color:#b71c1c; background:#b71c1c; }
.provider-page button:disabled { opacity:.5; cursor:not-allowed; }
.resource-table-scroll { overflow-x:auto; }
.resource-table { width:100%; min-width:1050px; border-collapse:collapse; text-align:left; }
.resource-table th,.resource-table td { padding:14px 16px; border-top:1px solid #edf1f3; font-size:12px; white-space:nowrap; }
.resource-table th { background:#f7f9fa; color:#6d8090; }
.resource-table td { max-width:230px; overflow:hidden; text-overflow:ellipsis; color:#344b59; }
.resource-table td.provider-empty { height:130px; text-align:center; color:#91a0ac; }
.provider-status { color:#208269; }
.provider-status.is-off { color:#aa685c; }
.provider-dialog { width:min(480px,100%); padding:24px; }
.provider-dialog--wide { width:min(760px,100%); }
.provider-dialog header,.provider-dialog footer { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.provider-dialog h2 { margin:0; font-size:18px; }
.provider-dialog header button { font-size:20px; }
.provider-fields { display:grid; gap:14px; margin:24px 0; }
.provider-fields label { display:grid; gap:6px; font-size:12px; color:#344b59; }
.provider-fields p { margin:0; color:#8a9ca8; font-size:12px; }
.provider-form-group { display:grid; gap:10px; padding-top:14px; border-top:1px solid #edf1f3; }
.provider-form-group h3 { margin:0; font-size:14px; }
.provider-form-row { display:flex; align-items:end; flex-wrap:wrap; gap:10px; padding:12px; border:1px solid #edf1f3; border-radius:9px; }
.provider-form-row label { flex:1; min-width:160px; }
.provider-form-row input { width:100%; box-sizing:border-box; }
.provider-form-label { min-width:115px; align-self:center; font-size:12px; color:#607685; }
.provider-form-row button { align-self:end; }
.provider-dialog footer { justify-content:flex-end; }
.provider-confirm { margin:26px 0; font-size:14px; }
.provider-section { margin-top:22px; padding-top:14px; border-top:1px solid #edf1f3; }
.provider-section h3 { margin:0 0 12px; font-size:14px; }
.provider-section p { font-size:12px; color:#8a9ca8; }
.provider-connection { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin:8px 0; padding:10px; border:1px solid #edf1f3; border-radius:9px; font-size:12px; }
.provider-connection div { flex:1; min-width:160px; overflow:hidden; }
.provider-connection small { display:block; margin-top:4px; overflow:hidden; text-overflow:ellipsis; }
.provider-inline-form { display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }
.provider-inline-form input { flex:1; min-width:140px; }
@media (max-width:560px) { .provider-hero { align-items:flex-start; flex-direction:column; } }
</style>
