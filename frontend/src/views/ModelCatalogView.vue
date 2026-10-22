<script setup lang="ts">
import { computed, ref, watch } from "vue";

import AppPagination from "@/AppPagination.vue";
import TokenCapacityHelp from "@/TokenCapacityHelp.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import AppListFilter from "@/AppListFilter.vue";
import AppSelect from "@/AppSelect.vue";
import { createAccessModel, listAccessModels, updateAccessModel } from "@/api/models";
import { listProtocols, listProviders, listSecrets, type ProviderProtocol, type ProviderSecret } from "@/api/providers";
import { t } from "@/i18n";
import { useAuthStore } from "@/stores/auth";
import type { AccessModelItem, PriceTier, ProviderItem } from "@/types/resource";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
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
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
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
  max_output_tokens: null as number | null,
  price_unit_k: 1, input_price: null as number | null, output_price: null as number | null,
  tiered_pricing: false, input_price_tiers: [] as PriceTier[],
  output_price_tiers: [] as PriceTier[],
});
type TierField = "input_price_tiers" | "output_price_tiers";

function toggleTiered(enabled: boolean) {
  form.value.tiered_pricing = enabled;
  if (enabled) {
    for (const field of ["input_price_tiers", "output_price_tiers"] as const) {
      if (!form.value[field].length) {
        form.value[field] = [{ up_to_tokens: null, price: form.value[
          field === "input_price_tiers" ? "input_price" : "output_price"
        ] ?? 0 }];
      }
    }
  }
}

function addTier(field: TierField) {
  const tiers = form.value[field];
  const last = tiers[tiers.length - 1];
  const previous = tiers.length > 1 ? tiers[tiers.length - 2].up_to_tokens ?? 0 : 0;
  last.up_to_tokens = previous + 1000;
  tiers.push({ up_to_tokens: null, price: last.price });
}

function removeTier(field: TierField, index: number) {
  const tiers = form.value[field];
  if (tiers.length <= 1) return;
  tiers.splice(index, 1);
  tiers[tiers.length - 1].up_to_tokens = null;
}
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
      filters: filters.value,
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
    max_output_tokens: item?.max_output_tokens ?? null,
    price_unit_k: item?.price_unit_k ?? 1, input_price: item?.input_price ?? null,
    output_price: item?.output_price ?? null,
    tiered_pricing: item?.tiered_pricing ?? false,
    input_price_tiers: item?.input_price_tiers.map((tier) => ({ ...tier })) ?? [],
    output_price_tiers: item?.output_price_tiers.map((tier) => ({ ...tier })) ?? [],
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
  if (form.value.tiered_pricing) {
    for (const field of ["input_price_tiers", "output_price_tiers"] as const) {
      const tiers = form.value[field];
      if (!tiers.length || tiers.some((tier, index) => !Number.isFinite(tier.price)
        || tier.price < 0 || (index < tiers.length - 1 && (
          !Number.isInteger(tier.up_to_tokens) || (tier.up_to_tokens ?? 0) <= (
            index ? tiers[index - 1].up_to_tokens ?? 0 : 0
          )
        )))) {
        showToast("error", t("请填写有效且严格递增的阶梯 Token 上限与单价"));
        return;
      }
    }
  }
  busy.value = true;
  try {
    const payload = {
      provider_id: form.value.provider_id, protocol_id: form.value.protocol_id,
      secret_id: form.value.secret_id || null, access_model_code: form.value.access_model_code,
      provider_model_name: form.value.provider_model_name, model_type: form.value.model_type,
      base_url: form.value.base_url.trim() || null, region: form.value.region || null,
      max_concurrency: form.value.max_concurrency || null,
      context_window: form.value.context_window || null, timeout_ms: form.value.timeout_ms || null,
      max_output_tokens: form.value.max_output_tokens || null,
      price_unit_k: form.value.price_unit_k, input_price: form.value.input_price,
      output_price: form.value.output_price,
      tiered_pricing: form.value.tiered_pricing,
      input_price_tiers: form.value.input_price_tiers,
      output_price_tiers: form.value.output_price_tiers,
    };
    if (editing.value) await updateAccessModel(editing.value.id, {
      protocol_id: payload.protocol_id, secret_id: payload.secret_id,
      provider_model_name: payload.provider_model_name, model_type: payload.model_type,
      base_url: payload.base_url, region: payload.region,
      max_concurrency: payload.max_concurrency, context_window: payload.context_window,
      max_output_tokens: payload.max_output_tokens,
      timeout_ms: payload.timeout_ms,
      price_unit_k: payload.price_unit_k, input_price: payload.input_price,
      output_price: payload.output_price,
      tiered_pricing: payload.tiered_pricing,
      input_price_tiers: payload.input_price_tiers,
      output_price_tiers: payload.output_price_tiers,
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

function applyFilters(value: FilterGroup) {
  filters.value = value;
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
        <AppFilterTags :fields="listFilterFields['access-models']" :model-value="filters" @apply="applyFilters" />
        <div class="catalog-filter"><AppSelect :model-value="filterProvider" :options="providerOptions" :aria-label="t('筛选供应商')" @update:model-value="changeFilter" />
          <button type="button" :disabled="loading" @click="load">{{ t("刷新") }}</button>
          <AppListFilter :fields="listFilterFields['access-models']" :model-value="filters" hide-tags @apply="applyFilters" />
        </div>
      </div>
      <div class="catalog-scroll"><table>
        <thead><tr><th>{{ t("平台内部模型编码") }}</th><th>{{ t("上游模型名") }}</th><th>{{ t("供应商") }}</th><th>{{ t("类型") }}</th><th>{{ t("协议") }}</th><th>{{ t("模型 Base URL") }}</th><th>{{ t("密钥") }}</th><th>{{ t("地域") }}</th><th>{{ t("输入/输出价格（元）") }}</th><th>{{ t("最大并发") }}</th><th>{{ t("最大 Token 容量") }}<TokenCapacityHelp /></th><th>{{ t("超时时间（毫秒）") }}</th><th>{{ t("状态") }}</th><th>{{ t("操作") }}</th></tr></thead>
        <tbody>
          <tr v-for="item in records" :key="item.id">
            <td>{{ item.access_model_code }}</td><td>{{ item.provider_model_name }}</td>
            <td>{{ providers.find((provider) => provider.id === item.provider_id)?.name ?? `#${item.provider_id}` }}</td>
            <td>{{ item.model_type }}</td><td>{{ item.protocol_id ?? "-" }}</td>
            <td :title="item.effective_base_url ?? ''">{{ item.effective_base_url ?? "-" }}<span v-if="!item.base_url" class="catalog-inherited">（{{ t("继承供应商") }}）</span></td>
            <td>{{ item.secret_id ?? t("无需密钥") }}</td>
            <td>{{ item.region || "-" }}</td>
            <td>{{ item.tiered_pricing ? `阶梯定价 · 输入 ${item.input_price_tiers.length} 档 / 输出 ${item.output_price_tiers.length} 档 · 每 ${item.price_unit_k}k Token` : item.currency !== "CNY" ? "历史 USD 价格（需重新定价）" : item.input_price == null || item.output_price == null ? "未定价" : `${Number(item.input_price).toFixed(2)} / ${Number(item.output_price).toFixed(2)} / ${item.price_unit_k}k Token` }}</td>
            <td>{{ item.max_concurrency ?? "-" }}</td>
            <td>{{ item.context_window ?? "-" }}</td><td>{{ item.timeout_ms ?? "-" }}</td>
            <td>{{ t(item.status === 1 ? "启用" : "停用") }}</td>
            <td><span v-if="!admin">-</span><div v-else class="catalog-actions"><button type="button" @click="openForm(item)">{{ t("编辑") }}</button>
              <button type="button" :class="{ 'is-danger': item.status === 1 }" @click="confirmTarget = item">{{ t(item.status === 1 ? "停用" : "启用") }}</button></div></td>
          </tr>
          <tr v-if="!records.length"><td colspan="14" class="catalog-empty">{{ t(loading ? "正在加载数据..." : "暂无匹配记录") }}</td></tr>
        </tbody>
      </table></div>
      <AppPagination v-if="total" v-model="page" v-model:page-size="pageSize" :total="total" :disabled="loading" />
    </div>
    <div v-if="formOpen" class="app-modal-overlay" v-backdrop-close="closeForm">
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
          <div class="catalog-capacity-field"><div><label for="model-token-capacity">最大 Token 容量</label><TokenCapacityHelp /></div><input id="model-token-capacity" v-model.number="form.context_window" type="number" min="1" max="2147483647" placeholder="选填，该节点可容纳的最大 Token 数量" /></div>
          <div class="catalog-capacity-field"><div><label for="model-output-tokens">最大输出 Token</label><TokenCapacityHelp kind="output" /></div><input id="model-output-tokens" v-model.number="form.max_output_tokens" type="number" min="1" max="2147483647" placeholder="选填，留空不额外限制输出" /></div>
          <label>{{ t("超时时间（毫秒）") }}<input v-model.number="form.timeout_ms" type="number" min="1" max="600000" :placeholder="t('选填')" /></label>
          <label>{{ t("计价单位（N 千 Token）") }}<input v-model.number="form.price_unit_k" type="number" min="1" max="1000000" required /></label>
          <label class="catalog-full catalog-pricing-toggle"><input type="checkbox" :checked="form.tiered_pricing" @change="toggleTiered(($event.target as HTMLInputElement).checked)" />{{ t("开启阶梯定价（输入和输出分别按本次 Token 长度选档，整段按命中档计价）") }}</label>
          <template v-if="!form.tiered_pricing">
            <label>{{ t("输入单价（人民币元）") }}<input :value="form.input_price ?? ''" type="number" min="0" step="0.01" placeholder="未定价" @input="form.input_price = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)" /></label>
            <label>{{ t("输出单价（人民币元）") }}<input :value="form.output_price ?? ''" type="number" min="0" step="0.01" placeholder="未定价" @input="form.output_price = ($event.target as HTMLInputElement).value === '' ? null : Number(($event.target as HTMLInputElement).value)" /></label>
          </template>
          <div v-for="side in (['input_price_tiers', 'output_price_tiers'] as const)" v-if="form.tiered_pricing" :key="side" class="catalog-full catalog-tier-list">
            <div class="catalog-tier-heading"><strong>{{ t(side === 'input_price_tiers' ? "输入 Token 阶梯" : "输出 Token 阶梯") }}</strong><button type="button" @click="addTier(side)">{{ t("添加档位") }}</button></div>
            <div v-for="(tier, index) in form[side]" :key="index" class="catalog-tier-row">
              <span>{{ index === 0 ? "0" : (form[side][index - 1].up_to_tokens ?? 0) + 1 }} ~</span>
              <input v-if="index < form[side].length - 1" v-model.number="tier.up_to_tokens" type="number" min="1" max="2147483647" required :aria-label="`${side === 'input_price_tiers' ? '输入' : '输出'}第 ${index + 1} 档 Token 上限`" />
              <span v-else>{{ t("不限 Token") }}</span>
              <span>{{ t(`每 ${form.price_unit_k}k Token ¥`) }}</span>
              <input v-model.number="tier.price" type="number" min="0" step="0.01" required :aria-label="`${side === 'input_price_tiers' ? '输入' : '输出'}第 ${index + 1} 档单价`" />
              <button type="button" :disabled="form[side].length === 1" @click="removeTier(side, index)">{{ t("删除") }}</button>
            </div>
          </div>
        </div>
        <footer><button type="button" :disabled="busy" @click="closeForm">{{ t("取消") }}</button><button type="submit" :disabled="busy || !form.interface_type || !form.protocol_id">{{ t(busy ? "保存中..." : "保存") }}</button></footer>
      </form>
    </div>
    <div v-if="confirmTarget" class="app-modal-overlay app-modal-overlay--confirmation" v-backdrop-close="() => { !busy && (confirmTarget = null) }">
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
.catalog-capacity-field{display:grid;gap:6px;min-width:0;font-size:12px}
.catalog-capacity-field>div{display:flex;align-items:center}
.catalog-fields .app-select { width:100%; }
.catalog-fields .catalog-full { grid-column:1/-1; }
.catalog-fields p { margin:0; font-size:12px; color:#a36539; }
.catalog-fields input { min-width:0; min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; font:inherit; }
.catalog-fields .catalog-pricing-toggle { display:flex; align-items:center; gap:8px; }
.catalog-fields .catalog-pricing-toggle input { width:16px; height:16px; min-height:auto; padding:0; }
.catalog-tier-list { display:grid; gap:9px; padding:12px; border:1px solid #dbe5e9; border-radius:10px; }
.catalog-tier-heading { display:flex; justify-content:space-between; align-items:center; }
.catalog-tier-row { display:grid; grid-template-columns:auto minmax(100px,1fr) auto minmax(100px,1fr) auto; align-items:center; gap:8px; font-size:12px; }
@media (max-width:560px) { .catalog-tier-row { grid-template-columns:auto minmax(90px,1fr) auto; } .catalog-tier-row input:nth-of-type(2) { grid-column:2; } }
@media (max-width:560px) { .catalog-heading { align-items:flex-start; flex-direction:column; } .catalog-fields { grid-template-columns:1fr; } .catalog-fields .catalog-full { grid-column:auto; } }
</style>
