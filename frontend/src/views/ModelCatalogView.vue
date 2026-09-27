<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppPagination from "@/AppPagination.vue";
import AppSelect from "@/AppSelect.vue";
import { createAccessModel, listAccessModels, updateAccessModel } from "@/api/models";
import { listProtocols, listProviders, listSecrets, type ProviderProtocol, type ProviderSecret } from "@/api/providers";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import type { AccessModelItem, ProviderItem } from "@/types/resource";
import { showToast } from "@/utils/toast";

const auth = useAuthStore();
const admin = computed(() => auth.userInfo?.roles.includes("platform_admin") ?? false);
const records = ref<AccessModelItem[]>([]);
const providers = ref<ProviderItem[]>([]);
const protocols = ref<ProviderProtocol[]>([]);
const secrets = ref<ProviderSecret[]>([]);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const filterProvider = ref(0);
const loading = ref(false);
const busy = ref(false);
const editing = ref<AccessModelItem | null>(null);
const formOpen = ref(false);
const confirmTarget = ref<AccessModelItem | null>(null);
const form = ref({
  provider_id: 0, protocol_id: 0, secret_id: 0,
  access_model_code: "", provider_model_name: "", model_type: "llm", interface_type: "",
  base_url: "", region: "", max_concurrency: null as number | null,
  context_window: null as number | null, timeout_ms: null as number | null,
});
let requestId = 0;
let refRequestId = 0;
const modelTypeOptions = ["llm", "vlm", "embedding", "rerank", "ocr", "text_to_image", "asr", "tts"].map((value) => ({ label: value.toUpperCase(), value }));
const interfaceTypeOptions = ["openai", "gemini", "claude"].map((value) => ({ label: value === "openai" ? "OpenAI" : value === "gemini" ? "Gemini" : "Claude", value }));
function interfaceType(protocolType: string) {
  if (protocolType === "openai_compatible" || protocolType === "openai") return "openai";
  if (protocolType === "anthropic" || protocolType === "claude") return "claude";
  return protocolType === "gemini" ? "gemini" : "";
}
const providerOptions = computed(() => [
  { label: t("全部供应商"), value: 0 },
  ...providers.value.map((item) => ({ label: item.name, value: item.id })),
]);
const protocolOptions = computed(() => protocols.value.filter((item) => interfaceType(item.protocol_type) === form.value.interface_type).map((item) => ({
  label: `${item.code} · ${item.protocol_type}`, value: item.id, disabled: item.status !== 1,
})));
const secretOptions = computed(() => [
  { label: t("无需密钥"), value: 0 },
  ...secrets.value.map((item) => ({ label: item.name, value: item.id, disabled: item.status !== 1 })),
]);
const selectedProvider = computed(() => providers.value.find((item) => item.id === form.value.provider_id));

function message(reason: unknown) {
  return (reason as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    || (reason instanceof Error ? reason.message : "操作失败，请重试");
}

async function load() {
  const id = ++requestId;
  loading.value = true;
  records.value = [];
  try {
    const result = await listAccessModels({
      page: page.value, page_size: pageSize.value,
      ...(filterProvider.value ? { provider_id: filterProvider.value } : {}),
    });
    if (id !== requestId) return;
    records.value = result.items;
    total.value = result.total;
  } catch (reason) {
    if (id === requestId) showToast("error", t(message(reason)));
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function loadProviders() {
  try {
    const first = await listProviders({ page: 1, page_size: 100, keyword: "" });
    const items = [...first.items];
    for (let nextPage = 2; items.length < first.total; nextPage += 1) {
      const result = await listProviders({ page: nextPage, page_size: 100, keyword: "" });
      if (!result.items.length) break;
      items.push(...result.items);
    }
    providers.value = items;
  } catch (reason) {
    showToast("error", t(message(reason)));
  }
}

async function chooseProvider(value: string | number) {
  const id = ++refRequestId;
  const providerId = Number(value);
  form.value.provider_id = providerId;
  form.value.protocol_id = 0;
  form.value.secret_id = 0;
  form.value.interface_type = "";
  form.value.base_url = "";
  protocols.value = [];
  secrets.value = [];
  if (!providerId) return;
  try {
    const [nextProtocols, nextSecrets] = await Promise.all([
      listProtocols(providerId), admin.value ? listSecrets(providerId) : Promise.resolve([]),
    ]);
    if (id !== refRequestId) return;
    protocols.value = nextProtocols;
    secrets.value = nextSecrets;
  } catch (reason) {
    if (id === refRequestId) showToast("error", t(message(reason)));
  }
}

function chooseInterface(value: string | number) {
  form.value.interface_type = String(value);
  form.value.protocol_id = 0;
  form.value.base_url = "";
}

function chooseProtocol(value: string | number) {
  form.value.protocol_id = Number(value);
  form.value.base_url = "";
}

function closeForm() {
  if (busy.value) return;
  refRequestId++;
  formOpen.value = false;
}

async function openForm(item: AccessModelItem | null = null) {
  editing.value = item;
  form.value = {
    provider_id: item?.provider_id ?? 0, protocol_id: 0, secret_id: 0,
    access_model_code: item?.access_model_code ?? "",
    provider_model_name: item?.provider_model_name ?? "", model_type: item?.model_type ?? "llm",
    interface_type: "",
    base_url: item?.base_url ?? "", region: item?.region ?? "",
    max_concurrency: item?.max_concurrency ?? null,
    context_window: item?.context_window ?? null, timeout_ms: item?.timeout_ms ?? null,
  };
  formOpen.value = true;
  if (item) {
    await chooseProvider(item.provider_id);
    form.value.interface_type = interfaceType(protocols.value.find((protocol) => protocol.id === item.protocol_id)?.protocol_type ?? "");
    form.value.protocol_id = item.protocol_id ?? 0;
    form.value.secret_id = item.secret_id ?? 0;
    form.value.base_url = item.base_url ?? "";
  }
}

async function save() {
  if (!form.value.provider_id || !form.value.interface_type || !form.value.protocol_id || busy.value) return;
  busy.value = true;
  try {
    const payload = {
      provider_id: form.value.provider_id, protocol_id: form.value.protocol_id,
      secret_id: form.value.secret_id || null, access_model_code: form.value.access_model_code,
      provider_model_name: form.value.provider_model_name, model_type: form.value.model_type,
      base_url: form.value.base_url.trim() || null, region: form.value.region || null,
      max_concurrency: form.value.max_concurrency || null,
      context_window: form.value.context_window || null, timeout_ms: form.value.timeout_ms || null,
    };
    if (editing.value) await updateAccessModel(editing.value.id, {
      protocol_id: payload.protocol_id, secret_id: payload.secret_id,
      provider_model_name: payload.provider_model_name, model_type: payload.model_type,
      base_url: payload.base_url, region: payload.region,
      max_concurrency: payload.max_concurrency, context_window: payload.context_window,
      timeout_ms: payload.timeout_ms,
    });
    else await createAccessModel(payload);
    formOpen.value = false;
    showToast("success", t(editing.value ? "已保存更改" : "创建成功"));
    await load();
  } catch (reason) {
    showToast("error", t(message(reason)));
  } finally {
    busy.value = false;
  }
}

async function confirmStatus() {
  if (!confirmTarget.value || busy.value) return;
  busy.value = true;
  try {
    await updateAccessModel(confirmTarget.value.id, { status: confirmTarget.value.status === 1 ? 0 : 1 });
    confirmTarget.value = null;
    showToast("success", t("状态已更新"));
    await load();
  } catch (reason) {
    showToast("error", t(message(reason)));
  } finally {
    busy.value = false;
  }
}

function changeFilter(value: string | number) {
  filterProvider.value = Number(value);
  if (page.value !== 1) page.value = 1;
  else void load();
}

void loadProviders();
watch([page, pageSize], () => void load(), { immediate: true });
</script>

<template>
  <section class="page-stack catalog-page">
    <header class="page-card catalog-heading">
      <div><h1>{{ t("模型管理") }}</h1><p>{{ t("管理供应商接入模型；对外模型在聚合模型中发布。") }}</p></div>
      <button v-if="admin" class="page-action" type="button" @click="openForm()">{{ t("新建模型") }}</button>
    </header>
    <div class="page-card catalog-card">
      <div class="catalog-toolbar">
        <h2>{{ t("供应商模型") }} · {{ total }}</h2>
        <div class="catalog-filter"><AppSelect :model-value="filterProvider" :options="providerOptions" :aria-label="t('筛选供应商')" @update:model-value="changeFilter" />
          <button type="button" :disabled="loading" @click="load">{{ t("刷新") }}</button></div>
      </div>
      <div class="catalog-scroll"><table>
        <thead><tr><th>{{ t("平台内部模型编码") }}</th><th>{{ t("上游模型名") }}</th><th>{{ t("供应商") }}</th><th>{{ t("类型") }}</th><th>{{ t("协议") }}</th><th>{{ t("模型 Base URL") }}</th><th>{{ t("密钥") }}</th><th>{{ t("地域") }}</th><th>{{ t("最大并发") }}</th><th>{{ t("最大 Token 容量") }}</th><th>{{ t("超时时间（毫秒）") }}</th><th>{{ t("状态") }}</th><th>{{ t("操作") }}</th></tr></thead>
        <tbody>
          <tr v-for="item in records" :key="item.id">
            <td>{{ item.access_model_code }}</td><td>{{ item.provider_model_name }}</td>
            <td>{{ providers.find((provider) => provider.id === item.provider_id)?.name ?? `#${item.provider_id}` }}</td>
            <td>{{ item.model_type }}</td><td>{{ item.protocol_id ?? "-" }}</td>
            <td :title="item.effective_base_url ?? ''">{{ item.effective_base_url ?? "-" }}<span v-if="!item.base_url" class="catalog-inherited">（{{ t("继承供应商") }}）</span></td>
            <td>{{ item.secret_id ?? t("无需密钥") }}</td>
            <td>{{ item.region || "-" }}</td><td>{{ item.max_concurrency ?? "-" }}</td>
            <td>{{ item.context_window ?? "-" }}</td><td>{{ item.timeout_ms ?? "-" }}</td>
            <td>{{ t(item.status === 1 ? "启用" : "停用") }}</td>
            <td><span v-if="!admin">-</span><div v-else class="catalog-actions"><button type="button" @click="openForm(item)">{{ t("编辑") }}</button>
              <button type="button" :class="{ 'is-danger': item.status === 1 }" @click="confirmTarget = item">{{ t(item.status === 1 ? "停用" : "启用") }}</button></div></td>
          </tr>
          <tr v-if="!records.length"><td colspan="13" class="catalog-empty">{{ t(loading ? "正在加载数据..." : "暂无匹配记录") }}</td></tr>
        </tbody>
      </table></div>
      <AppPagination v-if="total" v-model="page" v-model:page-size="pageSize" :total="total" :disabled="loading" />
    </div>
    <div v-if="formOpen" class="app-modal-overlay" @click.self="closeForm">
      <form class="app-modal-panel catalog-dialog" role="dialog" aria-modal="true" :aria-label="t(editing ? '编辑接入模型' : '新建模型')" @submit.prevent="save">
        <header><h2>{{ t(editing ? "编辑接入模型" : "新建模型") }}</h2><button type="button" aria-label="关闭" :disabled="busy" @click="closeForm">×</button></header>
        <div class="catalog-fields">
          <label>{{ t("供应商") }} *<AppSelect :model-value="form.provider_id || null" :options="providerOptions.filter((option) => option.value !== 0)" :disabled="Boolean(editing)" :aria-label="t('供应商')" :placeholder="t('请选择供应商')" @update:model-value="chooseProvider" /></label>
          <label>{{ t("平台内部模型编码") }} *<input v-model.trim="form.access_model_code" :disabled="Boolean(editing)" required maxlength="128" /></label>
          <label>{{ t("上游模型名") }} *<input v-model.trim="form.provider_model_name" required maxlength="128" /></label>
          <label>{{ t("模型类型") }} *<AppSelect v-model="form.model_type" :options="modelTypeOptions" :aria-label="t('模型类型')" /></label>
          <label>{{ t("接口类型") }} *<AppSelect :model-value="form.interface_type || null" :options="interfaceTypeOptions" :aria-label="t('接口类型')" :placeholder="t('请选择接口类型')" @update:model-value="chooseInterface" /></label>
          <label>{{ t("协议") }} *<AppSelect :model-value="form.protocol_id || null" :options="protocolOptions" :disabled="!form.interface_type" :aria-label="t('协议')" :placeholder="t('请选择协议')" @update:model-value="chooseProtocol" /></label>
          <p v-if="form.interface_type && !protocolOptions.length">{{ t("当前供应商尚未配置该接口类型的协议，请先前往供应商管理添加。") }}</p>
          <label class="catalog-full">{{ t("模型 Base URL（选填）") }}<input v-model.trim="form.base_url" type="url" maxlength="255" :placeholder="selectedProvider?.base_url || 'https://api.example.com/v1'" /></label>
          <p v-if="selectedProvider" class="catalog-full">{{ t("留空时继承供应商 Base URL，供应商地址更新后自动生效。") }}</p>
          <label>{{ t("上游 API Key") }}<AppSelect v-model="form.secret_id" :options="secretOptions" :aria-label="t('上游 API Key')" /></label>
          <label>{{ t("地域") }}<input v-model.trim="form.region" maxlength="64" /></label>
          <label>{{ t("最大并发") }}<input v-model.number="form.max_concurrency" type="number" min="1" max="100000" :placeholder="t('选填')" /></label>
          <label>{{ t("最大 Token 容量") }}<input v-model.number="form.context_window" type="number" min="1" max="2147483647" :placeholder="t('选填')" /></label>
          <label>{{ t("超时时间（毫秒）") }}<input v-model.number="form.timeout_ms" type="number" min="1" max="600000" :placeholder="t('选填')" /></label>
        </div>
        <footer><button type="button" :disabled="busy" @click="closeForm">{{ t("取消") }}</button><button type="submit" :disabled="busy || !form.interface_type || !form.protocol_id">{{ t(busy ? "保存中..." : "保存") }}</button></footer>
      </form>
    </div>
    <div v-if="confirmTarget" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!busy && (confirmTarget = null)">
      <div class="app-modal-panel catalog-dialog" role="alertdialog" aria-modal="true" :aria-label="t('确认操作')">
        <header><h2>{{ t("确认操作") }}</h2></header>
        <p>{{ t(`确定${confirmTarget.status === 1 ? "停用" : "启用"} ${confirmTarget.access_model_code} 吗？`) }}</p>
        <footer><button type="button" :disabled="busy" @click="confirmTarget = null">{{ t("取消") }}</button><button type="button" :class="{ 'catalog-confirm-danger': confirmTarget.status === 1 }" :disabled="busy" @click="confirmStatus">{{ t("确认") }}</button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.catalog-heading { display:flex; justify-content:space-between; align-items:center; gap:18px; }
.catalog-heading h1 { margin:0 0 8px; font-size:23px; }
.catalog-heading p { margin:0; color:#8a9ca8; font-size:12px; }
.catalog-card { padding:0; overflow:hidden; }
.catalog-toolbar { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px; padding:20px 24px; }
.catalog-toolbar h2 { margin:0; font-size:16px; }
.catalog-filter,.catalog-actions { display:flex; align-items:center; gap:8px; }
.catalog-filter .app-select { width:190px; }
.catalog-page button:not(.page-action) { padding:7px 12px; border:1px solid #d6e5e3; border-radius:9px; background:#f4faf8; color:#217c70; cursor:pointer; }
.catalog-page .catalog-actions button { min-height:34px; padding:4px 6px; border:0; background:transparent; color:#217c70; font:inherit; font-size:12px; }
.catalog-page .catalog-actions button:hover:not(:disabled) { text-decoration:underline; }
.catalog-page .catalog-actions button.is-danger { color:#d32f2f; font-weight:600; }
.catalog-page .catalog-actions button.is-danger:hover:not(:disabled) { color:#b71c1c; }
.catalog-page button.catalog-confirm-danger:not(.page-action) { border-color:#d32f2f; background:#d32f2f; color:#fff; }
.catalog-page button.catalog-confirm-danger:hover:not(:disabled) { border-color:#b71c1c; background:#b71c1c; }
.catalog-page button:disabled { opacity:.5; cursor:not-allowed; }
.catalog-scroll { overflow:auto; }
.catalog-scroll table { width:100%; min-width:1300px; border-collapse:collapse; text-align:left; }
.catalog-scroll th,.catalog-scroll td { padding:14px 17px; border-top:1px solid #edf1f3; font-size:12px; white-space:nowrap; }
.catalog-scroll td { max-width:260px; overflow:hidden; text-overflow:ellipsis; }
.catalog-inherited { color:#8296a2; }
.catalog-scroll th { background:#f7f9fa; color:#6d8090; }
.catalog-empty { height:130px; text-align:center; color:#91a0ac; }
.catalog-dialog { width:min(640px,100%); padding:24px; }
.catalog-dialog header,.catalog-dialog footer { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.catalog-dialog h2 { margin:0; font-size:18px; }
.catalog-dialog footer { justify-content:flex-end; }
.catalog-dialog p { margin:24px 0; }
.catalog-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:24px 0; }
.catalog-fields label { display:grid; gap:6px; min-width:0; font-size:12px; }
.catalog-fields .app-select { width:100%; }
.catalog-fields .catalog-full { grid-column:1/-1; }
.catalog-fields p { margin:0; font-size:12px; color:#a36539; }
.catalog-fields input { min-width:0; min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; font:inherit; }
@media (max-width:560px) { .catalog-heading { align-items:flex-start; flex-direction:column; } .catalog-fields { grid-template-columns:1fr; } .catalog-fields .catalog-full { grid-column:auto; } }
</style>
