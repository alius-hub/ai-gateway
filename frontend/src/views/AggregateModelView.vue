<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";

import AppSelect from "@/AppSelect.vue";
import { listAccessModels } from "@/api/models";
import { createAggregate, listAggregates, listBuiltinStrategies, updateAggregate,
  type AggregateItem, type AggregatePayload, type BuiltinStrategy, type StrategyCode } from "@/api/workflows";
import { useAuthStore } from "@/stores/auth";
import type { AccessModelItem } from "@/types/resource";
import { showToast } from "@/utils/toast";

const auth = useAuthStore();
const admin = computed(() => auth.userInfo?.roles.includes("platform_admin") ?? false);
const records = ref<AggregateItem[]>([]);
const strategies = ref<BuiltinStrategy[]>([]);
const models = ref<AccessModelItem[]>([]);
const editing = ref<AggregateItem | null>(null);
const confirmTarget = ref<AggregateItem | null>(null);
const open = ref(false);
const busy = ref(false);
const form = ref<AggregatePayload>(empty());
const fallbackSource = ref<"candidates" | "catalog">("candidates");
const types = ["llm", "vlm", "embedding", "rerank", "ocr", "text_to_image", "asr", "tts"].map((value) => ({ label: value.toUpperCase(), value }));
const fallbackSources = [
  { label: "聚合节点（当前候选）", value: "candidates" },
  { label: "模型管理（全部同类型）", value: "catalog" },
];
const strategyOptions = computed(() => strategies.value.map((strategy) => ({ label: strategy.name, value: strategy.code })));
const modelOptions = computed(() => models.value.filter((model) => model.model_type === form.value.model_type)
  .map((model) => ({
    value: model.id, label: `${model.access_model_code}${model.status !== 1 ? "（停用）" : ""}`,
  })));
const fallbackOptions = computed(() => fallbackSource.value === "candidates"
  ? modelOptions.value.filter((option) => form.value.routing_model_ids.includes(option.value))
  : modelOptions.value);
function empty(): AggregatePayload {
  return { aggregate_model_code: "", public_model_name: "", model_type: "llm",
    default_routing_strategy: "single", routing_model_ids: [0], fallback_model_id: null,
    description: null, status: 0 };
}
function isBuiltin(code: string): code is StrategyCode {
  return code === "single" || code === "round_robin" || code === "least_latency";
}
function errorMessage(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : error instanceof Error ? error.message : "操作失败";
}
async function load() {
  records.value = [];
  try {
    const [aggregates, builtin, first] = await Promise.all([
      listAggregates(), listBuiltinStrategies(), listAccessModels({ page: 1, page_size: 100 }),
    ]);
    records.value = aggregates.items;
    strategies.value = builtin.items;
    const all = [...first.items];
    for (let page = 2; all.length < first.total; page++) {
      const next = await listAccessModels({ page, page_size: 100 });
      if (!next.items.length) break;
      all.push(...next.items);
    }
    models.value = all;
  } catch (error) { showToast("error", errorMessage(error)); }
}
function edit(item: AggregateItem | null = null) {
  editing.value = item;
  form.value = item ? {
    aggregate_model_code: item.aggregate_model_code, public_model_name: item.public_model_name,
    model_type: item.model_type,
    default_routing_strategy: isBuiltin(item.default_routing_strategy) ? item.default_routing_strategy : "single",
    routing_model_ids: item.routing_model_ids.length ? [...item.routing_model_ids] : [0],
    fallback_model_id: item.fallback_model_id,
    description: item.description, status: item.status,
  } : empty();
  fallbackSource.value = item?.fallback_model_id && !form.value.routing_model_ids.includes(item.fallback_model_id)
    ? "catalog" : "candidates";
  open.value = true;
}
function setStrategy(value: string | number) {
  const code = String(value);
  if (!isBuiltin(code)) return;
  form.value.default_routing_strategy = code;
  form.value.routing_model_ids = code === "single" ? [0] : [0, 0];
}
function resetModelsForType() {
  form.value.routing_model_ids = form.value.default_routing_strategy === "single" ? [0] : [0, 0];
  form.value.fallback_model_id = null;
}
function setFallbackSource(value: string | number) {
  if (value !== "candidates" && value !== "catalog") return;
  fallbackSource.value = value;
  if (form.value.fallback_model_id && !fallbackOptions.value.some((option) => option.value === form.value.fallback_model_id)) {
    form.value.fallback_model_id = null;
  }
}
watch(() => form.value.routing_model_ids.slice(), (ids) => {
  if (fallbackSource.value === "candidates" && form.value.fallback_model_id && !ids.includes(form.value.fallback_model_id)) {
    form.value.fallback_model_id = null;
  }
});
async function save() {
  if (!admin.value || busy.value) return;
  busy.value = true;
  try {
    if (editing.value) await updateAggregate(editing.value.id, form.value);
    else await createAggregate(form.value);
    open.value = false;
    await load();
    showToast("success", "聚合模型已保存");
  } catch (error) { showToast("error", errorMessage(error)); }
  finally { busy.value = false; }
}
async function toggle(item: AggregateItem) {
  if (!admin.value || busy.value || !isBuiltin(item.default_routing_strategy)) return false;
  busy.value = true;
  try {
    await updateAggregate(item.id, {
      aggregate_model_code: item.aggregate_model_code, public_model_name: item.public_model_name,
      model_type: item.model_type, default_routing_strategy: item.default_routing_strategy,
      routing_model_ids: item.routing_model_ids, fallback_model_id: item.fallback_model_id,
      description: item.description,
      status: item.status === 1 ? 0 : 1,
    });
    await load();
    showToast("success", "状态已更新");
    return true;
  } catch (error) { showToast("error", errorMessage(error)); return false; }
  finally { busy.value = false; }
}
async function confirmStop() {
  const target = confirmTarget.value;
  if (target && await toggle(target)) confirmTarget.value = null;
}
onMounted(() => { void load(); });
</script>

<template>
  <div class="page-stack">
    <div class="page-card">
      <div class="aggregate-heading">
        <div><h2>聚合模型</h2><p>直接选择内置路由策略和接入模型。当前仅保存管理配置，真实网关发布与授权尚未接通。</p></div>
        <button v-if="admin" class="page-action" type="button" @click="edit()">新建聚合模型</button>
      </div>
      <div v-if="!records.length" class="aggregate-empty">暂无聚合模型。请先在 <RouterLink to="/models">模型管理</RouterLink> 配置接入模型。</div>
      <div v-else class="aggregate-table-wrap">
        <table><thead><tr><th>对外模型名</th><th>聚合编码</th><th>类型</th><th>路由策略</th><th>候选模型</th><th>兜底模型</th><th>配置状态</th><th>操作</th></tr></thead>
          <tbody><tr v-for="item in records" :key="item.id">
            <td>{{ item.public_model_name }}</td><td>{{ item.aggregate_model_code }}</td><td>{{ item.model_type.toUpperCase() }}</td>
            <td>{{ strategies.find((strategy) => strategy.code === item.default_routing_strategy)?.name ?? "旧配置" }}</td>
            <td>{{ item.routing_model_ids.length ? item.routing_model_ids.map((id) => models.find((model) => model.id === id)?.access_model_code ?? `#${id}`).join("、") : "待转换" }}</td>
            <td>{{ item.fallback_model_id ? models.find((model) => model.id === item.fallback_model_id)?.access_model_code ?? `#${item.fallback_model_id}` : "未配置" }}</td>
            <td>{{ item.status === 1 ? "已启用配置" : "已停用" }}</td>
            <td><button v-if="admin" type="button" @click="edit(item)">编辑</button>
              <button v-if="admin && isBuiltin(item.default_routing_strategy)" type="button"
                :class="{ danger: item.status === 1 }" :disabled="busy"
                @click="item.status === 1 ? (confirmTarget = item) : toggle(item)">{{ item.status === 1 ? "停用" : "启用" }}</button>
            </td>
          </tr></tbody>
        </table>
      </div>
    </div>
    <div v-if="open" class="app-modal-overlay" @click.self="!busy && (open = false)">
      <div class="app-modal-panel aggregate-modal aggregate-modal--form" role="dialog" aria-modal="true" aria-label="聚合模型配置">
        <h2>{{ editing ? "编辑聚合模型" : "新建聚合模型" }}</h2>
        <form class="aggregate-form" @submit.prevent="save">
          <p v-if="editing && !isBuiltin(editing.default_routing_strategy)" class="aggregate-notice">这是旧版路由配置。请选择内置策略与接入模型，保存后切换到新配置；原流程数据仍会保留。</p>
          <label>聚合编码<input v-model="form.aggregate_model_code" required :disabled="!!editing" maxlength="128" placeholder="例如 Chat.Pro_中文-01" /></label>
          <label>对外模型名称<input v-model="form.public_model_name" required maxlength="128" placeholder="例如 Chat.Pro_中文-01" /></label>
          <p>编码和对外名称支持中文、大小写字母、数字、下划线、连字符和小数点，不包含空格。</p>
          <label>模型类型<AppSelect v-model="form.model_type" :disabled="!!editing" :options="types" @update:model-value="resetModelsForType" /></label>
          <label>路由策略<AppSelect :model-value="form.default_routing_strategy" :options="strategyOptions" @update:model-value="setStrategy" /></label>
          <p>{{ strategies.find((strategy) => strategy.code === form.default_routing_strategy)?.description }}</p>
          <div class="aggregate-candidates">
            <strong>接入模型{{ form.default_routing_strategy === "single" ? "（固定 1 个）" : "（至少 2 个，按选择顺序排列）" }}</strong>
            <div v-for="(_modelId, index) in form.routing_model_ids" :key="index" class="aggregate-candidate">
              <AppSelect v-model="form.routing_model_ids[index]" :options="modelOptions" placeholder="选择接入模型" />
              <button v-if="form.default_routing_strategy !== 'single' && form.routing_model_ids.length > 2" type="button"
                aria-label="移除候选模型" @click="form.routing_model_ids.splice(index, 1)">×</button>
            </div>
            <button v-if="form.default_routing_strategy !== 'single' && form.routing_model_ids.length < 30"
              type="button" @click="form.routing_model_ids.push(0)">+ 添加候选模型</button>
          </div>
          <div class="aggregate-fallback">
            <strong>兜底模型（选填）</strong>
            <p>策略没有选中可用模型时使用；上游请求失败后的切换尚未接入网关。</p>
            <label>选择来源<AppSelect :model-value="fallbackSource" :options="fallbackSources" @update:model-value="setFallbackSource" /></label>
            <div class="aggregate-candidate">
              <AppSelect :model-value="form.fallback_model_id" :options="fallbackOptions" placeholder="不配置兜底模型"
                @update:model-value="form.fallback_model_id = Number($event)" />
              <button v-if="form.fallback_model_id" type="button" @click="form.fallback_model_id = null">清除</button>
            </div>
          </div>
          <label>说明<input v-model="form.description" maxlength="255" placeholder="可选" /></label>
          <p>轮询及最低延迟目前仅支持配置与模拟；尚无真实网关计数器或实时延迟采集。</p>
          <div class="aggregate-actions">
            <button type="button" :disabled="busy" @click="open = false">取消</button>
            <button class="page-action" type="submit" :disabled="busy || !strategies.length">保存</button>
          </div>
        </form>
      </div>
    </div>
    <div v-if="confirmTarget" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="!busy && (confirmTarget = null)">
      <div class="app-modal-panel aggregate-modal" role="alertdialog" aria-modal="true" aria-label="停用聚合模型">
        <h2>确认停用</h2>
        <p>确定停用聚合模型「{{ confirmTarget.public_model_name }}」吗？</p>
        <div class="aggregate-actions"><button type="button" :disabled="busy" @click="confirmTarget = null">取消</button>
          <button class="aggregate-danger" type="button" :disabled="busy" @click="confirmStop">确定停用</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.aggregate-heading,.aggregate-actions{display:flex;align-items:center;justify-content:space-between;gap:14px}
h2{margin:0 0 8px;font-size:20px}p{margin:0;color:#64748b;font-size:13px;line-height:1.5}
.aggregate-empty{margin-top:24px;padding:32px;text-align:center;background:#f7fafb;border-radius:10px;color:#64748b}
.aggregate-empty a{color:#168d81}.aggregate-table-wrap{overflow:auto;margin-top:24px}table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}
td,th{padding:16px 12px;border-bottom:1px solid #e2e8f0}th{color:#64748b;font-size:13px}td{font-size:14px}
td button,.aggregate-actions button{border:0;background:transparent;color:#146d70;padding:8px;cursor:pointer}
td button.danger{color:#c93636}.aggregate-modal{width:min(580px,calc(100vw - 32px));padding:24px}
.aggregate-modal--form{width:min(720px,calc(100vw - 32px))}
.aggregate-form{display:grid;gap:16px;margin-top:18px}.aggregate-form label{display:grid;gap:7px;color:#475569;font-size:13px}
.aggregate-form input{min-height:38px;padding:8px 10px;border:1px solid #d8e1e9;border-radius:8px}
.aggregate-candidates{display:grid;gap:10px;padding:14px;border:1px solid #d8e1e9;border-radius:10px}
.aggregate-fallback{display:grid;gap:10px;padding:14px;border:1px solid #d8e1e9;border-radius:10px}
.aggregate-candidate{display:flex;align-items:center;gap:8px;min-width:0}.aggregate-candidate .app-select{min-width:0;flex:1}
.aggregate-candidates button,.aggregate-fallback button{justify-self:start;border:0;background:none;color:#146d70;cursor:pointer}
.aggregate-notice{padding:10px 12px;border-radius:8px;background:#fff7ed;color:#9a3412}
.aggregate-actions{justify-content:flex-end}.aggregate-actions .page-action{color:#176c61}
.aggregate-modal > .aggregate-actions{margin-top:24px}.aggregate-actions .aggregate-danger{border-radius:8px;background:#c93636;color:white;padding:9px 16px}.aggregate-actions .aggregate-danger:hover{background:#aa2020}
</style>
