<script setup lang="ts">
import { computed, onUnmounted, ref } from "vue";
import { isAxiosError } from "axios";

import AppPagination from "@/AppPagination.vue";
import AppSelect from "@/AppSelect.vue";
import AppListFilter from "@/AppListFilter.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import type { FilterField, FilterGroup } from "@/types/filter";
import {
  actionAlertEvent, deleteAlertRule, getFeishuConfig, listAlertDeliveries,
  listAlertEvents, listAlertRules, saveAlertRule, saveFeishuConfig, testFeishuConfig, testAlertRule,
  type AlertEvent, type AlertRule, type AlertRulePayload, type Delivery, type FeishuConfig, type Metric, type TestPushResult,
} from "@/api/alerts";
import { showToast } from "@/utils/toast";
import { listIdentity, type IdentityRecord } from "@/api/identity";

const metricNames: Record<Metric, string> = {
  error_rate: "请求 5xx 错误率",
  key_token_usage: "Key 周期 Token 使用率",
  project_amount_usage: "项目累计金额预算使用率",
};
const metricOptions = Object.entries(metricNames).map(([value, label]) => ({ value, label }));
const tab = ref<"events" | "rules">("events");
const eventFilters = ref<FilterGroup>({ mode: "and", conditions: [] });
const ruleFilters = ref<FilterGroup>({ mode: "and", conditions: [] });
const commonFilterFields: FilterField[] = [
  { key: "id", label: "ID", type: "number" },
  { key: "rule_name", label: "规则名称", type: "text" },
  { key: "metric", label: "指标", type: "select", options: metricOptions },
  { key: "level", label: "级别", type: "select", options: [
    { label: "警告", value: "warning" }, { label: "严重", value: "critical" },
  ] },
  { key: "scope_type", label: "范围类型", type: "select", options: [
    { label: "平台", value: "platform" }, { label: "项目", value: "project" }, { label: "Key", value: "key" },
  ] },
  { key: "scope_id", label: "项目 / Key ID", type: "number" },
  { key: "threshold", label: "阈值 (%)", type: "decimal" },
];
const eventFilterFields: FilterField[] = [...commonFilterFields,
  { key: "status", label: "事件状态", type: "select", options: [
    { label: "未确认", value: "open" }, { label: "已确认", value: "acknowledged" }, { label: "已恢复", value: "resolved" },
  ] },
  { key: "current_value", label: "当前值 (%)", type: "decimal" },
  { key: "triggered_at", label: "触发日期", type: "date" },
  { key: "acknowledged_at", label: "确认日期", type: "date" },
  { key: "resolved_at", label: "恢复日期", type: "date" },
];
const ruleFilterFields: FilterField[] = [...commonFilterFields,
  { key: "enabled", label: "启用状态", type: "select", options: [
    { label: "启用", value: "1" }, { label: "停用", value: "0" },
  ] },
  { key: "window_minutes", label: "时间窗（分钟）", type: "number" },
  { key: "min_samples", label: "最小请求数", type: "number" },
  { key: "created_at", label: "创建日期", type: "date" },
];
function applyFilters(value: FilterGroup) {
  if (tab.value === "events") {
    eventFilters.value = value;
    page.value = 1;
    void loadEvents();
  } else {
    ruleFilters.value = value;
    rulePage.value = 1;
    void loadRules();
  }
}
const events = ref<AlertEvent[]>([]);
const rules = ref<AlertRule[]>([]);
const deliveries = ref<Delivery[]>([]);
const selectedEvent = ref<number | null>(null);
const page = ref(1);
const total = ref(0);
const pageSize = ref(20);
const rulePage = ref(1);
const rulePageSize = ref(20);
const ruleTotal = ref(0);
const rulesLoading = ref(false);
const status = ref("all");
const loading = ref(false);
const saving = ref(false);
const settingsOpen = ref(false);
const ruleOpen = ref(false);
const deleteTarget = ref<AlertRule | null>(null);
const testingRuleId = ref<number | null>(null);
const testResults = ref<TestPushResult[]>([]);
const testResultName = ref<string | null>(null);
const editId = ref<number | undefined>();
const config = ref<FeishuConfig>({ app_id: "", chat_id: "", enabled: true, has_secret: false });
const secret = ref("");
const projects = ref<IdentityRecord[]>([]);
const loadingProjects = ref(false);
const projectLoadFailed = ref(false);
let projectGeneration = 0;
const form = ref<AlertRulePayload>({
  name: "", metric: "error_rate", scope_id: null, threshold: 10,
  window_minutes: 5, min_samples: 10, level: "warning", enabled: true, recipients: [],
});
let generation = 0;
let ruleGeneration = 0;
let disposed = false;

const scopeSelection = computed<string | number>({
  get: () => form.value.scope_id ?? (form.value.metric === "error_rate" ? "platform" : ""),
  set: value => { form.value.scope_id = value === "platform" ? null : Number(value); },
});
const scopeOptions = computed(() => {
  const options: { label: string; value: string | number; disabled?: boolean }[] =
    form.value.metric === "error_rate" ? [{ label: "平台（全部项目）", value: "platform" }] : [];
  options.push(...projects.value.map(project => ({
    value: project.id,
    label: `${project.name || project.code || `项目 #${project.id}`} (${project.code || project.id})${project.status !== 1 ? '（停用）' : ''}${form.value.metric === 'project_amount_usage' && !project.amount_budget ? '（未配置预算）' : ''}`,
    disabled: project.status !== 1 || (form.value.metric === "project_amount_usage" && !project.amount_budget),
  })));
  if (form.value.scope_id && !projects.value.some(project => project.id === form.value.scope_id)) {
    options.push({ label: `项目 #${form.value.scope_id}（不可用）`, value: form.value.scope_id, disabled: true });
  }
  return options;
});

async function loadProjects() {
  const current = ++projectGeneration;
  loadingProjects.value = true;
  projectLoadFailed.value = false;
  try {
    const items: IdentityRecord[] = [];
    for (let projectPage = 1; ; projectPage++) {
      const result = await listIdentity("projects", { page: projectPage, page_size: 100 });
      if (disposed || current !== projectGeneration) return;
      items.push(...result.items);
      if (items.length >= result.total || !result.items.length) break;
    }
    projects.value = items;
  } catch {
    if (!disposed && current === projectGeneration) {
      projectLoadFailed.value = true;
      showToast("error", "加载项目选项失败，请重试");
    }
  } finally {
    if (current === projectGeneration) loadingProjects.value = false;
  }
}

function scopeLabel(metric: Metric, id: number | null) {
  if (metric === "key_token_usage") return `Key #${id}`;
  if (id === null) return "平台";
  return projects.value.find(project => project.id === id)?.name || `项目 #${id}`;
}

async function loadEvents() {
  const current = ++generation;
  loading.value = true;
  events.value = [];
  selectedEvent.value = null;
  deliveries.value = [];
  try {
    const result = await listAlertEvents(page.value, status.value === "all" ? undefined : status.value, eventFilters.value, pageSize.value);
    if (disposed || current !== generation) return;
    events.value = result.items;
    total.value = result.total;
    const lastPage = Math.max(1, Math.ceil(result.total / pageSize.value));
    if (page.value > lastPage) { page.value = lastPage; await loadEvents(); }
  } catch {
    if (!disposed && current === generation) showToast("error", "加载告警事件失败");
  } finally {
    if (current === generation) loading.value = false;
  }
}

async function loadRules() {
  const current = ++ruleGeneration;
  rulesLoading.value = true;
  rules.value = [];
  try {
    const result = await listAlertRules(rulePage.value, rulePageSize.value, ruleFilters.value);
    if (disposed || current !== ruleGeneration) return;
    rules.value = result.items;
    ruleTotal.value = result.total;
    const lastPage = Math.max(1, Math.ceil(result.total / rulePageSize.value));
    if (rulePage.value > lastPage) { rulePage.value = lastPage; await loadRules(); }
  } catch {
    if (!disposed && current === ruleGeneration) showToast("error", "加载告警规则失败");
  } finally {
    if (current === ruleGeneration) rulesLoading.value = false;
  }
}

function changeEventPageSize(value: number) {
  pageSize.value = value;
  page.value = 1;
  void loadEvents();
}

function changeRulePageSize(value: number) {
  rulePageSize.value = value;
  rulePage.value = 1;
  void loadRules();
}

async function openSettings() {
  try {
    config.value = await getFeishuConfig();
    secret.value = "";
    settingsOpen.value = true;
  } catch { showToast("error", "加载飞书配置失败"); }
}

function closeSettings() {
  secret.value = "";
  settingsOpen.value = false;
}

async function saveSettings() {
  saving.value = true;
  try {
    await saveFeishuConfig({
      app_id: config.value.app_id.trim(), chat_id: config.value.chat_id.trim(),
      enabled: config.value.enabled, ...(secret.value ? { app_secret: secret.value } : {}),
    });
    showToast("success", "飞书设置已保存");
    closeSettings();
  } catch { showToast("error", "保存失败，请检查必填项及服务端加密主密钥"); }
  finally { saving.value = false; }
}

async function testSettings() {
  saving.value = true;
  try {
    await testFeishuConfig();
    showToast("success", "测试消息已发送");
  } catch (error) {
    const detail = isAxiosError(error) ? error.response?.data?.detail : undefined;
    showToast("error", typeof detail === "string" ? detail : "发送失败，请确认应用权限和目标群聊");
  }
  finally { saving.value = false; }
}

function openRule(rule?: AlertRule) {
  editId.value = rule?.id;
  form.value = rule ? {
    name: rule.name, metric: rule.metric, scope_id: rule.scope_id,
    threshold: Number(rule.threshold), window_minutes: rule.window_minutes,
    min_samples: rule.min_samples, level: rule.level, enabled: rule.enabled,
    recipients: (rule.recipients || []).map(item => ({ ...item })),
  } : {
    name: "", metric: "error_rate", scope_id: null, threshold: 10,
    window_minutes: 5, min_samples: 10, level: "warning", enabled: true, recipients: [],
  };
  ruleOpen.value = true;
  void loadProjects();
}

async function submitRule() {
  if (form.value.metric !== "key_token_usage" && (loadingProjects.value || projectLoadFailed.value)) return;
  if (form.value.metric === "project_amount_usage" && !form.value.scope_id) {
    showToast("error", "请选择项目");
    return;
  }
  saving.value = true;
  try {
    await saveAlertRule({
      ...form.value, name: form.value.name.trim(),
      scope_id: form.value.scope_id ? Number(form.value.scope_id) : null,
      recipients: form.value.recipients.map(item => ({ ...item, receive_id: item.receive_id.trim() })),
    }, editId.value);
    ruleOpen.value = false;
    showToast("success", "规则已保存");
    await loadRules();
  } catch { showToast("error", "保存失败，请检查对象 ID、额度配置及未结束事件"); }
  finally { saving.value = false; }
}

async function removeRule() {
  if (!deleteTarget.value) return;
  try {
    await deleteAlertRule(deleteTarget.value.id);
    deleteTarget.value = null;
    showToast("success", "规则已删除");
    await loadRules();
  } catch { showToast("error", "已有事件的规则不能删除，请改为停用"); }
}

async function pushRuleTest(rule: AlertRule) {
  if (testingRuleId.value !== null) return;
  testingRuleId.value = rule.id;
  testResultName.value = null;
  testResults.value = [];
  try {
    const result = await testAlertRule(rule.id);
    if (disposed) return;
    testResults.value = result.results;
    testResultName.value = rule.name;
    const failed = result.results.filter(item => !item.sent).length;
    showToast(failed ? "error" : "success", failed
      ? `测试推送完成，${failed} 个目标失败，请查看结果`
      : `测试消息已发送至 ${result.results.length} 个目标`);
  } catch (error) {
    if (disposed) return;
    const detail = isAxiosError(error) ? error.response?.data?.detail : undefined;
    showToast("error", typeof detail === "string" ? detail : "测试推送失败，请检查飞书应用设置");
  } finally {
    testingRuleId.value = null;
  }
}

async function changeEvent(event: AlertEvent, action: "ack" | "resolve") {
  try {
    await actionAlertEvent(event.id, action);
    showToast("success", action === "ack" ? "已确认" : "已恢复");
    await loadEvents();
  } catch { showToast("error", "操作失败，事件状态可能已变化"); }
}

async function showDeliveries(id: number) {
  if (selectedEvent.value === id) { selectedEvent.value = null; return; }
  try {
    deliveries.value = await listAlertDeliveries(id);
    selectedEvent.value = id;
  } catch { showToast("error", "加载投递记录失败"); }
}

function refresh() { if (tab.value === "events") void loadEvents(); else void loadRules(); }
onUnmounted(() => { disposed = true; generation++; events.value = []; rules.value = []; });
void loadEvents();
void loadRules();
void loadProjects();
</script>

<template>
  <section class="page-stack alerts-page">
    <div class="page-card alerts-header">
      <div><h2>告警中心</h2><p>查看运行告警、管理阈值规则及飞书应用消息通知。</p></div>
      <div class="header-actions">
        <button class="app-control-button" type="button" @click="refresh">刷新</button>
        <button class="app-control-button app-control-button--primary" type="button" @click="openSettings">飞书设置</button>
      </div>
    </div>
    <div class="page-card alerts-content">
      <div class="alerts-toolbar">
        <div class="tabs">
          <button :class="{ active: tab === 'events' }" type="button" @click="tab = 'events'">告警事件</button>
          <button :class="{ active: tab === 'rules' }" type="button" @click="tab = 'rules'">告警规则</button>
        </div>
        <div v-if="tab === 'events'" class="header-actions">
          <AppListFilter :fields="eventFilterFields" :model-value="eventFilters" hide-tags @apply="applyFilters" />
          <AppSelect v-model="status" class="status-select" placeholder="全部状态" :options="[
            { label: '全部状态', value: 'all' }, { label: '未确认', value: 'open' },
            { label: '已确认', value: 'acknowledged' }, { label: '已恢复', value: 'resolved' },
          ]" aria-label="告警状态筛选" @change="page = 1; loadEvents()" />
        </div>
        <div v-else class="header-actions">
          <AppListFilter :fields="ruleFilterFields" :model-value="ruleFilters" hide-tags @apply="applyFilters" />
          <button class="app-control-button app-control-button--primary" type="button" @click="openRule()">新增规则</button>
        </div>
      </div>
      <div v-if="(tab === 'events' ? eventFilters : ruleFilters).conditions.length" class="alerts-filter-tags">
        <AppFilterTags :fields="tab === 'events' ? eventFilterFields : ruleFilterFields" :model-value="tab === 'events' ? eventFilters : ruleFilters" @apply="applyFilters" />
      </div>
      <div class="table-wrap">
        <table v-if="tab === 'events'">
          <thead><tr><th>触发时间</th><th>规则</th><th>级别</th><th>指标 / 对象</th><th>当前 / 阈值</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <template v-for="event in events" :key="event.id">
              <tr>
                <td>{{ new Date(event.triggered_at).toLocaleString() }}</td>
                <td>{{ event.rule_name }}</td><td>{{ event.level === 'critical' ? '严重' : '警告' }}</td>
                <td>{{ metricNames[event.metric] }} / {{ scopeLabel(event.metric, event.scope_id) }}</td>
                <td>{{ Number(event.current_value).toFixed(2) }}% / {{ event.threshold }}%</td>
                <td>{{ { open: '未确认', acknowledged: '已确认', resolved: '已恢复' }[event.status] }}</td>
                <td class="actions">
                  <button v-if="event.status === 'open'" type="button" @click="changeEvent(event, 'ack')">确认</button>
                  <button v-if="event.status !== 'resolved'" type="button" @click="changeEvent(event, 'resolve')">手动恢复</button>
                  <button type="button" @click="showDeliveries(event.id)">投递记录</button>
                </td>
              </tr>
              <tr v-if="selectedEvent === event.id"><td colspan="7" class="delivery">
                <span v-if="!deliveries.length">暂无投递记录</span>
                <span v-for="item in deliveries" :key="item.id">
                  {{ item.receive_id_type === 'open_id' ? '用户' : '群聊' }} {{ item.receive_id || '自动查群' }} —
                  {{ item.kind === 'triggered' ? '触发' : '恢复' }}：{{ item.status }}
                  （尝试 {{ item.attempts }} 次）{{ item.last_error || '' }}
                </span>
              </td></tr>
            </template>
            <tr v-if="!events.length"><td colspan="7" class="empty">{{ loading ? '正在加载...' : '暂无告警事件' }}</td></tr>
          </tbody>
        </table>
        <table v-else>
          <thead><tr><th>名称</th><th>指标</th><th>告警范围</th><th>阈值</th><th>时间窗 / 最小样本</th><th>级别</th><th>接收目标</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="rule in rules" :key="rule.id">
              <td>{{ rule.name }}</td><td>{{ metricNames[rule.metric] }}</td><td>{{ scopeLabel(rule.metric, rule.scope_id) }}</td>
              <td>{{ rule.threshold }}%</td>
              <td>{{ rule.metric === 'error_rate' ? `${rule.window_minutes} 分钟 / ${rule.min_samples} 次` : '-' }}</td>
              <td>{{ rule.level === 'critical' ? '严重' : '警告' }}</td>
              <td><span v-if="!rule.recipients?.length">全局默认群</span><div v-for="target in rule.recipients" :key="target.receive_id_type + target.receive_id">{{ target.receive_id_type === 'open_id' ? '用户' : '群聊' }}：{{ target.receive_id }}</div></td>
              <td>{{ rule.enabled ? '启用' : '停用' }}</td>
              <td class="actions"><button type="button" @click="openRule(rule)">编辑</button><button type="button" :disabled="testingRuleId !== null" @click="pushRuleTest(rule)">{{ testingRuleId === rule.id ? '推送中...' : '测试推送' }}</button><button class="danger-action" type="button" @click="deleteTarget = rule">删除</button></td>
            </tr>
            <tr v-if="!rules.length"><td colspan="9" class="empty">{{ rulesLoading ? '正在加载...' : '暂无告警规则' }}</td></tr>
          </tbody>
        </table>
      </div>
      <AppPagination v-if="tab === 'events'" v-model="page" :total="total" :page-size="pageSize" :disabled="loading" @change="loadEvents" @update:page-size="changeEventPageSize" />
      <AppPagination v-else v-model="rulePage" :total="ruleTotal" :page-size="rulePageSize" :disabled="rulesLoading" @change="loadRules" @update:page-size="changeRulePageSize" />
    </div>

    <div v-if="settingsOpen" class="app-modal-overlay" @click.self="closeSettings">
      <form class="app-modal-panel alerts-modal" role="dialog" aria-modal="true" aria-label="飞书设置" @submit.prevent="saveSettings">
        <h3>飞书 SaaS 应用设置</h3>
        <p>机器人需要具备发送消息权限并加入目标群。群聊 ID 留空时自动查找唯一群聊，需具备群信息读取权限；机器人在多个群中时请指定群聊 ID。</p>
        <label><span>应用 ID <span class="required-mark" aria-hidden="true">*</span></span><input v-model="config.app_id" class="app-control-input" required maxlength="128" autocomplete="off" /></label>
        <label><span>应用密钥 <span v-if="!config.has_secret" class="required-mark" aria-hidden="true">*</span><span v-else>（已配置）</span></span><input v-model="secret" class="app-control-input" type="password" :required="!config.has_secret" autocomplete="new-password" :placeholder="config.has_secret ? '已配置，留空表示不修改' : '请输入应用密钥'" /></label>
        <label>全局默认群聊 ID（选填）<input v-model="config.chat_id" class="app-control-input" maxlength="128" placeholder="留空自动查找机器人所在的唯一群聊" /></label>
        <label class="inline"><input v-model="config.enabled" type="checkbox" /> 启用飞书通知</label>
        <div class="modal-actions">
          <button class="app-control-button" type="button" :disabled="saving || !config.has_secret" @click="testSettings">发送测试消息</button>
          <button class="app-control-button" type="button" @click="closeSettings">取消</button>
          <button class="app-control-button app-control-button--primary" :disabled="saving" type="submit">保存</button>
        </div>
      </form>
    </div>
    <div v-if="ruleOpen" class="app-modal-overlay" @click.self="ruleOpen = false">
      <form class="app-modal-panel alerts-modal" role="dialog" aria-modal="true" aria-label="告警规则" @submit.prevent="submitRule">
        <h3>{{ editId ? '编辑告警规则' : '新增告警规则' }}</h3>
        <label><span>规则名称 <span class="required-mark" aria-hidden="true">*</span></span><input v-model="form.name" class="app-control-input" required maxlength="128" /></label>
        <label><span>指标 <span class="required-mark" aria-hidden="true">*</span></span><AppSelect v-model="form.metric" :options="metricOptions" aria-label="指标" @change="form.scope_id = null" /></label>
        <label v-if="form.metric !== 'key_token_usage'"><span>告警范围 <span class="required-mark" aria-hidden="true">*</span></span><AppSelect v-model="scopeSelection" :options="scopeOptions" :disabled="loadingProjects || projectLoadFailed" :placeholder="loadingProjects ? '正在加载项目...' : '请选择项目'" aria-label="告警范围" /></label>
        <button v-if="projectLoadFailed && form.metric !== 'key_token_usage'" class="app-control-button" type="button" @click="loadProjects">重新加载项目</button>
        <label v-if="form.metric === 'key_token_usage'"><span>Key ID <span class="required-mark" aria-hidden="true">*</span></span><input v-model.number="form.scope_id" class="app-control-input" type="number" min="1" required placeholder="填写 Key ID" /></label>
        <label><span>阈值 (%) <span class="required-mark" aria-hidden="true">*</span></span><input v-model.number="form.threshold" class="app-control-input" type="number" step="0.01" min="0.01" max="100" required /></label>
        <template v-if="form.metric === 'error_rate'">
          <label><span>时间窗（分钟） <span class="required-mark" aria-hidden="true">*</span></span><input v-model.number="form.window_minutes" class="app-control-input" type="number" min="1" max="60" required /></label>
          <label><span>最小请求数 <span class="required-mark" aria-hidden="true">*</span></span><input v-model.number="form.min_samples" class="app-control-input" type="number" min="1" required /></label>
        </template>
        <label><span>级别 <span class="required-mark" aria-hidden="true">*</span></span><AppSelect v-model="form.level" :options="[{ value: 'warning', label: '警告' }, { value: 'critical', label: '严重' }]" aria-label="级别" /></label>
        <fieldset class="recipient-fieldset">
          <legend>通知接收目标</legend>
          <p>可同时添加多个用户和群聊。未添加时沿用全局默认群。用户需在机器人可用范围内，机器人需加入目标群。</p>
          <div v-for="(target, index) in form.recipients" :key="index" class="recipient-row">
            <label><span>类型 <span class="required-mark">*</span></span><AppSelect v-model="target.receive_id_type" :options="[{ value: 'open_id', label: '用户私聊' }, { value: 'chat_id', label: '群聊' }]" aria-label="接收目标类型" /></label>
            <label><span>{{ target.receive_id_type === 'open_id' ? '用户 Open ID' : '群聊 ID' }} <span class="required-mark">*</span></span><input v-model="target.receive_id" class="app-control-input" required maxlength="128" :placeholder="target.receive_id_type === 'open_id' ? 'ou_...' : 'oc_...'" /></label>
            <button class="recipient-remove" type="button" :aria-label="`移除第 ${index + 1} 个接收目标`" @click="form.recipients.splice(index, 1)">移除</button>
          </div>
          <button class="app-control-button" type="button" :disabled="form.recipients.length >= 50" @click="form.recipients.push({ receive_id_type: 'open_id', receive_id: '' })">添加接收目标</button>
        </fieldset>
        <label class="inline"><input v-model="form.enabled" type="checkbox" /> 启用规则</label>
        <div class="modal-actions">
          <button class="app-control-button" type="button" @click="ruleOpen = false">取消</button>
          <button class="app-control-button app-control-button--primary" :disabled="saving || (form.metric !== 'key_token_usage' && (loadingProjects || projectLoadFailed))" type="submit">保存</button>
        </div>
      </form>
    </div>
    <div v-if="testResultName !== null" class="app-modal-overlay" @click.self="testResultName = null">
      <div class="app-modal-panel alerts-modal" role="dialog" aria-modal="true" aria-label="测试推送结果">
        <h3>测试推送结果</h3><p>规则：{{ testResultName }}</p>
        <div v-for="(result, index) in testResults" :key="index" class="test-result">
          <strong>{{ result.receive_id_type === 'open_id' ? '用户私聊' : '群聊' }}：{{ result.receive_id || '全局自动查群' }}</strong>
          <span :class="{ 'required-mark': !result.sent }">{{ result.sent ? '发送成功' : result.error || '发送失败' }}</span>
        </div>
        <div class="modal-actions"><button class="app-control-button" type="button" @click="testResultName = null">关闭</button></div>
      </div>
    </div>
    <div v-if="deleteTarget" class="app-modal-overlay app-modal-overlay--confirmation" @click.self="deleteTarget = null">
      <div class="app-modal-panel alerts-modal" role="alertdialog" aria-modal="true" aria-label="删除规则">
        <h3>删除规则？</h3><p>已有事件的规则不能删除，可以在编辑中将其停用。</p>
        <div class="modal-actions">
          <button class="app-control-button" type="button" @click="deleteTarget = null">取消</button>
          <button class="app-control-button alerts-danger-button" type="button" @click="removeRule">确认删除</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.alerts-header,.alerts-toolbar,.header-actions,.tabs,.modal-actions{display:flex;align-items:center;gap:10px}
.alerts-header,.alerts-toolbar{justify-content:space-between;flex-wrap:wrap}
h2{margin:0 0 8px;font-size:20px}h3{margin:0;font-size:18px}
p{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.alerts-content{padding:0;overflow:hidden}.alerts-toolbar{padding:16px}
.alerts-filter-tags{padding:0 16px 12px}
.tabs button,.actions button{border:0;background:transparent;color:#287c70;cursor:pointer}
.actions button.danger-action{color:#c93636}.actions button.danger-action:hover{color:#aa2020}
.actions button:focus-visible{outline:2px solid currentColor;outline-offset:2px}
.alerts-danger-button{background:#c93636;border-color:#c93636;color:#fff}
.alerts-danger-button:hover:not(:disabled){background:#aa2020;border-color:#aa2020}
.tabs button{padding:8px 12px;color:#617887}.tabs button.active{color:#217c70;border-bottom:2px solid #217c70;font-weight:700}
.status-select{width:145px}.table-wrap{overflow:auto}
table{width:100%;min-width:860px;border-collapse:collapse;text-align:left}
th,td{padding:12px 16px;border-bottom:1px solid #edf1f3;font-size:12px;white-space:nowrap}
th{background:#f7f9fa;color:#6d8090}.actions{display:flex;gap:10px}.empty{text-align:center;padding:36px}
.delivery span{display:block;padding:4px 0}.alerts-modal{width:min(480px,calc(100vw - 32px));box-sizing:border-box;padding:24px;display:grid;gap:14px}
.alerts-modal label{display:grid;gap:6px;font-size:13px;color:#344957}
.required-mark{color:#c93636;margin-left:2px}
.recipient-fieldset{border:1px solid #e1e8ee;border-radius:8px;padding:14px;min-width:0;display:grid;gap:12px}
.recipient-fieldset legend{font-size:13px;padding:0 6px}.recipient-row{display:grid;grid-template-columns:110px minmax(0,1fr) 36px;gap:8px;align-items:end}
.recipient-remove{border:0;background:none;color:#c93636;cursor:pointer;padding:8px 0}
.actions button:disabled{opacity:.5;cursor:not-allowed}.test-result{display:grid;gap:6px;padding:12px;border:1px solid #e1e8ee;border-radius:8px;font-size:13px;overflow-wrap:anywhere}
.alerts-modal label.inline{display:flex;align-items:center}.modal-actions{justify-content:flex-end;flex-wrap:wrap}
</style>
