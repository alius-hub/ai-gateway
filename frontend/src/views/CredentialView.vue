<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppPagination from "@/AppPagination.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import AppListFilter from "@/AppListFilter.vue";
import AppSelect from "@/AppSelect.vue";
import {
  createCredential, listCredentials, revealCredential, rotateCredential, setCredentialStatus,
  updateCredential, type CredentialItem, type CredentialSecret, type CredentialSettings, type KeyScope,
} from "@/api/credentials";
import { listIdentity, listMembers, type IdentityRecord } from "@/api/identity";
import { listAccessModels } from "@/api/models";
import { listAggregates, type AggregateItem } from "@/api/workflows";
import { useAuthStore } from "@/stores/auth";
import type { AccessModelItem } from "@/types/resource";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
import { buildCurlExample, preferredShell, type CurlShell } from "@/utils/credentialExample";
import { showToast } from "@/utils/toast";

const route = useRoute();
const auth = useAuthStore();
const scope = computed<KeyScope>(() => route.path.endsWith("/personal") ? "user" : "project");
const title = computed(() => scope.value === "user" ? "个人 Key" : "项目 Key");
const admin = computed(() => auth.userInfo?.roles.includes("platform_admin") ?? false);
const rows = ref<CredentialItem[]>([]);
const owners = ref<IdentityRecord[]>([]);
const aggregates = ref<AggregateItem[]>([]);
const accessModels = ref<AccessModelItem[]>([]);
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
const loading = ref(false);
const busy = ref(false);
const editing = ref<CredentialItem | null>(null);
const formOpen = ref(false);
const ownerId = ref<number | null>(null);
const projectOwnerId = ref<number | "">("");
const projectMembers = ref<IdentityRecord[]>([]);
const membersLoading = ref(false);
const customPrefix = ref("");
const rotatePrefix = ref("");
const secret = ref("");
const secretModels = ref<CredentialSecret["models"]>([]);
const exampleModelId = ref("");
const curlShell = ref<CurlShell>(preferredShell(navigator.userAgent));
const viewing = ref(false);
const pending = ref<{ item: CredentialItem; action: "rotate" | "status" } | null>(null);
const form = ref<CredentialSettings>(emptyForm());
const example = computed(() => {
  const model = secretModels.value.find((item) => item.id === exampleModelId.value);
  return model && secret.value
    ? buildCurlExample(secret.value, model, window.location.origin, curlShell.value)
    : null;
});
let requestId = 0;
let membersRequestId = 0;

function emptyForm(): CredentialSettings {
  return {
    name: "", aggregate_model_ids: [], access_model_ids: [],
    expires_at: null, tpm_limit: null, qps_limit: null, token_budget: null, amount_budget: null,
    budget_period: null, wait_mode: "block", max_wait_ms: 30000,
  };
}

function message(reason: unknown): string {
  const detail = (reason as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "操作失败，请重试";
}

async function load() {
  if (!admin.value) return;
  const id = ++requestId;
  const currentScope = scope.value;
  rows.value = [];
  loading.value = true;
  try {
    const result = await listCredentials(currentScope, page.value, pageSize.value, filters.value);
    if (id !== requestId || currentScope !== scope.value) return;
    rows.value = result.items;
    total.value = result.total;
  } catch (reason) {
    if (id === requestId) showToast("error", message(reason));
  } finally {
    if (id === requestId) loading.value = false;
  }
}

async function loadChoices() {
  const currentScope = scope.value;
  try {
    const [ownerPages, aggregatePage, modelPages] = await Promise.all([
      fetchAllOwners(currentScope), listAggregates(), fetchAllModels(),
    ]);
    if (currentScope !== scope.value) return;
    owners.value = ownerPages.filter((item) => item.status === 1);
    aggregates.value = aggregatePage.items.filter((item) => item.status === 1 && !item.workflow_id);
    accessModels.value = modelPages.filter((item) => item.status === 1);
  } catch (reason) {
    showToast("error", message(reason));
  }
}

async function fetchAllOwners(currentScope: KeyScope): Promise<IdentityRecord[]> {
  const kind = currentScope === "user" ? "users" : "projects";
  const all: IdentityRecord[] = [];
  for (let index = 1; ; index++) {
    const result = await listIdentity(kind, { page: index, page_size: 100 });
    all.push(...result.items);
    if (all.length >= result.total) return all;
  }
}

async function fetchAllModels(): Promise<AccessModelItem[]> {
  const all: AccessModelItem[] = [];
  for (let index = 1; ; index++) {
    const result = await listAccessModels({ page: index, page_size: 100 });
    all.push(...result.items);
    if (all.length >= result.total) return all;
  }
}

function openForm(item: CredentialItem | null = null) {
  editing.value = item;
  ownerId.value = scope.value === "project" ? item?.project_id ?? null : item?.user_id ?? null;
  projectOwnerId.value = "";
  projectMembers.value = [];
  customPrefix.value = "";
  form.value = item ? {
    name: item.name, aggregate_model_ids: [...item.aggregate_model_ids],
    access_model_ids: [...item.access_model_ids], expires_at: item.expires_at,
    tpm_limit: item.tpm_limit, qps_limit: item.qps_limit,
    token_budget: item.token_budget, amount_budget: item.amount_budget, budget_period: item.budget_period,
    wait_mode: item.wait_mode, max_wait_ms: item.max_wait_ms,
  } : emptyForm();
  formOpen.value = true;
  void loadChoices();
}

function openRotate(item: CredentialItem) {
  rotatePrefix.value = item.custom_prefix ?? "";
  pending.value = { item, action: "rotate" };
}

function validPrefix(value: string): boolean {
  if (!value || /^[A-Za-z][A-Za-z0-9_-]{1,19}$/.test(value)) return true;
  showToast("error", "自定义前缀须为 2-20 位，以字母开头，仅含字母、数字、_ 或 -");
  return false;
}

function showSecret(result: CredentialSecret) {
  secret.value = result.api_key;
  secretModels.value = result.models;
  exampleModelId.value = result.models.find((item) =>
    ["llm", "vlm", "embedding", "rerank", "ocr", "text_to_image"].includes(item.model_type),
  )?.id ?? result.models[0]?.id ?? "";
  curlShell.value = preferredShell(navigator.userAgent);
}

function closeSecret() {
  secret.value = "";
  secretModels.value = [];
  exampleModelId.value = "";
}

async function openSecret(item: CredentialItem) {
  if (viewing.value || !item.revealable) return;
  const currentScope = scope.value;
  viewing.value = true;
  try {
    const result = await revealCredential(currentScope, item.id);
    if (currentScope === scope.value) showSecret(result);
  } catch (reason) {
    showToast("error", message(reason));
  } finally {
    viewing.value = false;
  }
}

function toggle(field: "aggregate_model_ids" | "access_model_ids", id: number, checked: boolean) {
  const list = form.value[field];
  form.value[field] = checked ? [...list, id] : list.filter((item) => item !== id);
}

async function save() {
  if (busy.value) return;
  if (!editing.value && !validPrefix(customPrefix.value)) return;
  if (ownerId.value === null && !editing.value) {
    showToast("error", `请选择${scope.value === "user" ? "用户" : "项目"}`);
    return;
  }
  if (!form.value.aggregate_model_ids.length && !form.value.access_model_ids.length) {
    showToast("error", "至少绑定一个模型");
    return;
  }
  busy.value = true;
  try {
    const payload = { ...form.value, name: form.value.name.trim() };
    if (editing.value) {
      await updateCredential(scope.value, editing.value.id, payload);
    } else {
      const result = await createCredential(scope.value, {
        ...payload, custom_prefix: customPrefix.value || null,
        [scope.value === "user" ? "user_id" : "project_id"]: ownerId.value!,
        ...(scope.value === "project" && projectOwnerId.value !== ""
          ? { user_id: Number(projectOwnerId.value) } : {}),
      });
      showSecret(result);
    }
    formOpen.value = false;
    showToast("success", editing.value ? "已保存更改" : "Key 已创建");
    await load();
  } catch (reason) {
    showToast("error", message(reason));
  } finally {
    busy.value = false;
  }
}

async function confirmAction() {
  if (!pending.value || busy.value) return;
  if (pending.value.action === "rotate" && !validPrefix(rotatePrefix.value)) return;
  busy.value = true;
  try {
    const { item, action } = pending.value;
    if (action === "rotate") {
      const result = await rotateCredential(scope.value, item.id, rotatePrefix.value || null);
      showSecret(result);
    } else {
      await setCredentialStatus(scope.value, item.id, item.status === 1 ? 0 : 1);
    }
    pending.value = null;
    showToast("success", action === "rotate" ? "Key 已轮换" : "状态已更新");
    await load();
  } catch (reason) {
    showToast("error", message(reason));
  } finally {
    busy.value = false;
  }
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(secret.value);
    showToast("success", "已复制，请妥善保管");
  } catch {
    showToast("error", "复制失败，请手动选中密钥");
  }
}

async function copyExample() {
  if (!example.value) return;
  try {
    await navigator.clipboard.writeText(example.value);
    showToast("success", "调用示例已复制");
  } catch {
    showToast("error", "复制失败，请手动选择示例文本");
  }
}

function ownerName(item: CredentialItem): string {
  const id = scope.value === "project" ? item.project_id : item.user_id;
  const owner = owners.value.find((candidate) => candidate.id === id);
  return owner?.name ?? owner?.username ?? `#${id}`;
}

watch(ownerId, async (projectId) => {
  const id = ++membersRequestId;
  projectOwnerId.value = "";
  projectMembers.value = [];
  membersLoading.value = false;
  if (scope.value !== "project" || !formOpen.value || editing.value || projectId === null) return;
  membersLoading.value = true;
  try {
    const members = await listMembers("projects", projectId);
    if (id === membersRequestId && formOpen.value && ownerId.value === projectId) {
      projectMembers.value = members.filter((member) =>
        member.status === 1 && member.member_status === 1);
    }
  } catch (reason) {
    if (id === membersRequestId) showToast("error", message(reason));
  } finally {
    if (id === membersRequestId) membersLoading.value = false;
  }
});

watch([scope, page, pageSize], () => void load(), { immediate: true });
watch(scope, () => {
  ++membersRequestId;
  projectOwnerId.value = "";
  projectMembers.value = [];
  membersLoading.value = false;
  page.value = 1;
  filters.value = { mode: "and", conditions: [] };
  total.value = 0;
  owners.value = [];
  aggregates.value = [];
  accessModels.value = [];
  formOpen.value = false;
  pending.value = null;
  closeSecret();
  if (admin.value) void loadChoices();
}, { immediate: true });

function applyFilters(value: FilterGroup) {
  filters.value = value;
  if (page.value !== 1) page.value = 1;
  else void load();
}
</script>

<template>
  <section class="page-stack credential-page">
    <header class="page-card credential-hero">
      <div><h1>{{ title }} 管理</h1><p>统一配置模型授权、速率和周期用量；目前仅管理员可操作。</p></div>
      <button v-if="admin" class="page-action" type="button" @click="openForm()">新建{{ title }}</button>
    </header>
    <div class="page-card credential-notice">
      Key 鉴权、TPM/QPS、周/月额度及排队位置查询已接入网关；聊天支持 OpenAI、Claude、Gemini 文本协议及 SSE，其他模型接口需接入兼容相应路径的供应商。
    </div>
    <div v-if="admin" class="page-card credential-list">
      <div class="credential-toolbar"><h2>{{ title }}列表 <small>共 {{ total }} 条</small></h2>
        <AppFilterTags :fields="listFilterFields[scope === 'user' ? 'user-keys' : 'project-keys']" :model-value="filters" @apply="applyFilters" />
        <div class="app-list-toolbar-actions">
          <button type="button" @click="load">刷新</button>
          <AppListFilter :fields="listFilterFields[scope === 'user' ? 'user-keys' : 'project-keys']" :model-value="filters" hide-tags @apply="applyFilters" />
        </div>
      </div>
      <div class="credential-scroll">
        <table class="resource-table">
          <thead><tr><th>名称</th><th>{{ scope === "user" ? "用户" : "项目" }}</th><th v-if="scope === 'project'">归属人</th><th>前缀</th><th>模型绑定</th><th>TPM / QPS</th><th>周期额度</th><th>等待方式</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="item in rows" :key="item.id">
              <td>{{ item.name }}</td><td>{{ ownerName(item) }}</td>
              <td v-if="scope === 'project'">{{ item.owner_name ?? (item.user_id ? `#${item.user_id}` : "未指定") }}</td>
              <td><span class="credential-prefix">
                <code>{{ item.key_prefix }}…</code>
                <button class="credential-eye" type="button" :disabled="busy || viewing || !item.revealable"
                  :title="item.revealable ? '查看 API Key 和调用示例' : '历史 Key 无法恢复，轮换后可查看'"
                  :aria-label="item.revealable ? `查看 ${item.name} 的 API Key 和调用示例` : `${item.name} 为历史 Key，请轮换后查看`"
                  @click="openSecret(item)">
                  <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6S2 12 2 12Z" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                </button>
              </span></td>
              <td>聚合 {{ item.aggregate_model_ids.length }} / 直连 {{ item.access_model_ids.length }}</td>
              <td>{{ item.tpm_limit ?? "不限" }} / {{ item.qps_limit ?? "不限" }}</td>
              <td>{{ item.token_budget ? `${item.token_budget} Token` : "不限 Token" }} / {{ item.amount_budget != null ? `¥${Number(item.amount_budget).toFixed(2)}` : "不限金额" }}{{ item.budget_period ? ` / ${item.budget_period === "week" ? "周" : "月"}` : "" }}</td>
              <td>{{ item.wait_mode === "queue" ? "排队" : "阻塞" }}</td>
              <td>{{ item.status === 1 ? "启用" : "停用" }}</td>
              <td class="credential-actions">
                <button type="button" :disabled="busy" @click="openForm(item)">编辑</button>
                <button type="button" :disabled="busy" @click="openRotate(item)">轮换</button>
                <button type="button" :disabled="busy" :class="{ danger: item.status === 1 }" @click="pending = { item, action: 'status' }">{{ item.status === 1 ? "停用" : "启用" }}</button>
              </td>
            </tr>
            <tr v-if="!rows.length"><td :colspan="scope === 'project' ? 10 : 9" class="credential-empty">{{ loading ? "正在加载..." : "暂无 Key" }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination v-if="total" v-model="page" v-model:page-size="pageSize" :total="total" :disabled="loading" />
    </div>
    <div v-else class="page-card credential-notice">仅平台管理员可访问凭证管理。</div>

    <div v-if="formOpen" class="app-modal-overlay" @click.self="!busy && (formOpen = false)">
      <form class="app-modal-panel credential-dialog" role="dialog" aria-modal="true" :aria-label="editing ? '编辑 Key' : '新建 Key'" @submit.prevent="save">
        <header><h2>{{ editing ? "编辑" : "新建" }}{{ title }}</h2><button type="button" aria-label="关闭" :disabled="busy" @click="formOpen = false">×</button></header>
        <div class="credential-fields">
          <label>名称 *<input v-model.trim="form.name" required maxlength="128" /></label>
          <label v-if="!editing">{{ scope === "user" ? "所属用户" : "所属项目" }} *
            <AppSelect v-model="ownerId" :options="owners.map((item) => ({ label: `${item.name ?? item.username} (#${item.id})`, value: item.id }))" placeholder="请选择" />
          </label>
          <p v-else>归属：{{ ownerName(editing) }}。如需更改归属，请重新创建 Key。</p>
          <label v-if="scope === 'project' && !editing">归属人（选填，仅项目成员）
            <AppSelect v-model="projectOwnerId" :disabled="ownerId === null || membersLoading"
              :options="[{ label: '不指定归属人', value: '' }, ...projectMembers.map((member) => ({ label: `${member.username} (#${member.id})`, value: member.id }))]"
              :placeholder="membersLoading ? '正在加载项目成员...' : '不指定归属人'" />
          </label>
          <p v-if="scope === 'project' && editing">归属人：{{ editing.owner_name ?? (editing.user_id ? `#${editing.user_id}` : "未指定") }}。如需更改，请重新创建 Key。</p>
          <label v-if="!editing">自定义 Key 前缀（可选）
            <input v-model.trim="customPrefix" maxlength="20" placeholder="留空使用 agw_" pattern="[A-Za-z][A-Za-z0-9_-]{1,19}" title="2-20 位，以字母开头，仅含字母、数字、下划线或连字符" />
            <span>例如输入 team 会生成 team_ 开头的 Key；设置后可在轮换时修改。</span>
          </label>
          <p v-else>Key 前缀：{{ editing.custom_prefix ?? "agw_（默认）" }}。如需修改，请轮换 Key。</p>
          <fieldset><legend>聚合模型授权</legend>
            <p>可选多个已启用的聚合模型。</p>
            <div class="credential-choices">
              <label v-for="item in aggregates" :key="item.id">
                <input type="checkbox" :checked="form.aggregate_model_ids.includes(item.id)" @change="toggle('aggregate_model_ids', item.id, ($event.target as HTMLInputElement).checked)" />
                {{ item.public_model_name }} ({{ item.model_type }})
              </label>
              <span v-if="!aggregates.length">暂无可选聚合模型</span>
            </div>
          </fieldset>
          <fieldset><legend>直连接入模型（管理员专用）</legend>
            <p>直连绕过聚合路由及兜底，但仍应经过网关鉴权与计量。</p>
            <div class="credential-choices">
              <label v-for="item in accessModels" :key="item.id">
                <input type="checkbox" :checked="form.access_model_ids.includes(item.id)" @change="toggle('access_model_ids', item.id, ($event.target as HTMLInputElement).checked)" />
                {{ item.access_model_code }} ({{ item.model_type }})
              </label>
              <span v-if="!accessModels.length">暂无可选接入模型</span>
            </div>
          </fieldset>
          <div class="credential-grid">
            <label>TPM（空为不限）<input v-model.number="form.tpm_limit" type="number" min="1" placeholder="不限" @change="form.tpm_limit ||= null" /></label>
            <label>QPS（空为不限）<input v-model.number="form.qps_limit" type="number" min="1" placeholder="不限" @change="form.qps_limit ||= null" /></label>
            <label>周期 Token 上限<input v-model.number="form.token_budget" type="number" min="1" placeholder="不限" @change="form.token_budget ||= null; if (!form.token_budget && !form.amount_budget) form.budget_period = null" /></label>
            <label>周期金额上限（人民币元）<input v-model.number="form.amount_budget" type="number" min="0.01" step="0.01" placeholder="不限" @change="form.amount_budget ||= null; if (!form.token_budget && !form.amount_budget) form.budget_period = null" /></label>
            <label>统计周期<AppSelect :model-value="form.budget_period ?? ''" :options="[{ label: '不限制', value: '' }, { label: '自然周', value: 'week' }, { label: '自然月', value: 'month' }]" @update:model-value="form.budget_period = $event ? ($event as 'week' | 'month') : null" /></label>
            <label>等待模式<AppSelect v-model="form.wait_mode" :options="[{ label: '阻塞等待', value: 'block' }, { label: '排队返回票据', value: 'queue' }]" /></label>
            <label>最大等待时间（毫秒）<input v-model.number="form.max_wait_ms" type="number" min="1000" max="300000" required /></label>
            <label>过期时间（可选，UTC）<input :value="form.expires_at?.slice(0, 16) ?? ''" type="datetime-local" @change="form.expires_at = ($event.target as HTMLInputElement).value ? `${($event.target as HTMLInputElement).value}:00Z` : null" /></label>
          </div>
          <p>排队模式返回票据，可查询位置并携票据重试相同请求；阻塞模式达到等待上限返回 429。周/月额度按 UTC 自然周期统计；一个项目可创建多个 Key，共享项目累计金额预算。</p>
        </div>
        <footer><button type="button" :disabled="busy" @click="formOpen = false">取消</button><button type="submit" :disabled="busy">{{ busy ? "保存中..." : "保存" }}</button></footer>
      </form>
    </div>
    <div v-if="pending" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!busy && (pending = null)">
      <div class="app-modal-panel credential-confirm" role="alertdialog" aria-modal="true" aria-label="确认操作">
        <h2>确认{{ pending.action === "rotate" ? "轮换" : pending.item.status === 1 ? "停用" : "启用" }} Key</h2>
        <p>{{ pending.action === "rotate" ? "旧 Key 将立即失效；新 Key 可由管理员再次查看，请注意妥善保管。" : `确定修改「${pending.item.name}」的状态吗？` }}</p>
        <label v-if="pending.action === 'rotate'" class="credential-rotate-prefix">新 Key 前缀（可选）
          <input v-model.trim="rotatePrefix" maxlength="20" placeholder="留空使用 agw_" />
          <span>保留原值沿用已有前缀；留空重置为 agw_。</span>
        </label>
        <footer><button type="button" :disabled="busy" @click="pending = null">取消</button><button type="button" :class="{ danger: pending.action === 'rotate' || pending.item.status === 1 }" :disabled="busy" @click="confirmAction">确定</button></footer>
      </div>
    </div>
    <div v-if="secret" class="app-modal-overlay" @click.self="closeSecret">
      <div class="app-modal-panel credential-viewer" role="dialog" aria-modal="true" aria-label="API Key 和调用示例">
        <header class="credential-viewer-header"><h2>API Key 与调用示例</h2><button type="button" aria-label="关闭" @click="closeSecret">×</button></header>
        <p>仅平台管理员可再次查看。示例使用当前站点地址；请勿在截图、日志或聊天中传播密钥。</p>
        <label class="credential-viewer-label">API Key
          <input :value="secret" aria-label="API Key 明文" readonly @focus="($event.target as HTMLInputElement).select()" />
        </label>
        <div class="credential-viewer-controls">
          <label v-if="secretModels.length" class="credential-viewer-label">调用模型
            <AppSelect v-model="exampleModelId" :options="secretModels.map((item) => ({ label: `${item.id} (${item.model_type})`, value: item.id }))" />
          </label>
          <div class="credential-viewer-label">终端环境
            <div class="credential-shell">
              <button type="button" :class="{ active: curlShell === 'linux' }" :aria-pressed="curlShell === 'linux'" @click="curlShell = 'linux'">Linux / macOS</button>
              <button type="button" :class="{ active: curlShell === 'windows' }" :aria-pressed="curlShell === 'windows'" @click="curlShell = 'windows'">Windows PowerShell</button>
            </div>
          </div>
        </div>
        <pre v-if="example" class="credential-curl"><code>{{ example }}</code></pre>
        <p v-else>当前授权模型没有可用的调用示例。ASR / TTS 接口暂未接通网关。</p>
        <footer><button type="button" @click="copySecret">复制 Key</button><button type="button" :disabled="!example" @click="copyExample">复制 curl</button><button type="button" @click="closeSecret">关闭</button></footer>
      </div>
    </div>
  </section>
</template>

<style scoped>
.credential-hero,.credential-toolbar,.credential-dialog header,.credential-dialog footer,.credential-confirm footer { display:flex; justify-content:space-between; align-items:center; gap:12px; }
.credential-hero h1 { margin:0 0 8px; font-size:23px; }
.credential-hero p,.credential-fields p,.credential-notice { color:#697f8a; font-size:12px; }
.credential-notice { background:#fff9e9; }
.credential-list { padding:0; overflow:hidden; }
.credential-toolbar { padding:22px 24px; flex-wrap:wrap; }
.credential-toolbar h2 { margin:0; font-size:16px; }
.credential-toolbar small { font-size:12px; color:#8a9ca8; }
.credential-scroll { overflow-x:auto; }
.resource-table { width:100%; min-width:1050px; border-collapse:collapse; text-align:left; }
.resource-table th,.resource-table td { padding:14px; border-top:1px solid #edf1f3; font-size:12px; white-space:nowrap; }
.resource-table th { background:#f7f9fa; color:#6d8090; }
.credential-empty { text-align:center; height:120px; }
.credential-page button:not(.page-action) { min-height:34px; padding:6px 12px; border:1px solid #d6e5e3; border-radius:9px; background:#f4faf8; color:#217c70; cursor:pointer; }
.credential-page button:disabled { opacity:.5; cursor:not-allowed; }
.credential-actions button { border:0!important; background:transparent!important; }
.credential-prefix { display:flex; align-items:center; gap:5px; }
.credential-page .credential-eye { display:inline-flex; align-items:center; justify-content:center; min-width:30px; min-height:30px; padding:4px; border:0; background:transparent; color:#217c70; }
.credential-eye:focus-visible { outline:2px solid #217c70; outline-offset:2px; }
.credential-page button.danger { color:#c62f2f; }
.credential-confirm button.danger { background:#c62f2f!important; color:white!important; border-color:#c62f2f!important; }
.credential-dialog { width:min(760px,100%); padding:24px; }
.credential-confirm { width:min(500px,100%); padding:24px; }
.credential-viewer { width:min(720px,100%); padding:24px; }
.credential-viewer-header { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.credential-dialog h2,.credential-confirm h2,.credential-viewer h2 { margin:0; font-size:18px; }
.credential-rotate-prefix { display:grid; gap:8px; font-size:12px; }
.credential-rotate-prefix span,.credential-fields label span { color:#697f8a; font-size:12px; }
.credential-viewer p { color:#697f8a; font-size:12px; line-height:1.6; }
.credential-viewer-label { display:grid; gap:8px; min-width:0; font-size:12px; }
.credential-viewer-label input { width:100%; box-sizing:border-box; min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; font:inherit; }
.credential-viewer-controls { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:16px; align-items:end; margin-top:20px; }
.credential-shell { display:flex; gap:6px; flex-wrap:wrap; }
.credential-page .credential-shell button.active { background:#217c70; border-color:#217c70; color:#fff; }
.credential-curl { max-height:230px; overflow:auto; padding:14px; border-radius:9px; background:#102630; color:#e2f5ed; white-space:pre-wrap; overflow-wrap:anywhere; font-size:12px; line-height:1.6; }
.credential-viewer footer { display:flex; justify-content:flex-end; gap:8px; flex-wrap:wrap; margin-top:20px; }
.credential-fields { display:grid; gap:16px; margin:20px 0; }
.credential-fields label { display:grid; gap:6px; font-size:12px; }
.credential-fields input:not([type="checkbox"]),.credential-confirm input { width:100%; box-sizing:border-box; min-height:38px; padding:8px 11px; border:1px solid #dbe5e9; border-radius:9px; font:inherit; }
.credential-fields fieldset { min-width:0; border:1px solid #e1eaed; border-radius:9px; }
.credential-fields legend { font-size:14px; font-weight:600; }
.credential-choices { display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:8px; max-height:120px; overflow:auto; }
.credential-choices label { display:flex; align-items:center; gap:8px; }
.credential-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.credential-confirm p { margin:20px 0; line-height:1.6; }
.credential-confirm footer,.credential-dialog footer { justify-content:flex-end; margin-top:20px; }
@media(max-width:560px) { .credential-grid,.credential-viewer-controls { grid-template-columns:1fr; } .credential-hero { align-items:flex-start; flex-direction:column; } }
</style>
