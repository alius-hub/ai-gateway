<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";

import AppSelect from "@/AppSelect.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import AppListFilter from "@/AppListFilter.vue";
import { listAccessModels } from "@/api/models";
import { debugChat, deleteDebugHistory, executeDebug, getDebugHistory, listDebugHistory, type ChatMessage,
  type ChatRequest, type ChatResult, type DebugHistoryDetail, type DebugHistoryItem,
  type DebugMetadata, type RawRequest } from "@/api/playground";
import { listProtocols } from "@/api/providers";
import { listAggregates, type AggregateItem } from "@/api/workflows";
import { useAuthStore } from "@/stores/auth";
import type { AccessModelItem } from "@/types/resource";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
import { showToast } from "@/utils/toast";

const auth = useAuthStore();
const isAdmin = computed(() => auth.userInfo?.roles.includes("platform_admin") ?? false);
const models = ref<AccessModelItem[]>([]);
const aggregates = ref<AggregateItem[]>([]);
const source = ref<"access" | "aggregate" | "custom">("access");
const modelId = ref<number | null>(null);
const customProtocol = ref<"openai" | "openai_compatible" | "claude" | "anthropic" | "gemini">("openai_compatible");
const customBaseUrl = ref("");
const customModelName = ref("");
const customApiKey = ref("");
const systemPrompt = ref("");
const temperature = ref<number | null>(0.7);
const topP = ref<number | null>(1);
const maxTokens = ref<number | null>(1024);
const stopText = ref("");
const useHistory = ref(true);
const historyRounds = ref(10);
const messages = ref<ChatMessage[]>([]);
const draft = ref("");
const busy = ref(false);
const loading = ref(true);
const result = ref<ChatResult | null>(null);
const mode = ref<"conversation" | "raw">("conversation");
const streaming = ref(false);
const rawBody = ref("");
const rawHeaders = ref("{}");
const rawResponse = ref("");
const rawMetadata = ref<DebugMetadata | null>(null);
const streamingAnswer = ref("");
const controller = ref<AbortController | null>(null);
const historyItems = ref<DebugHistoryItem[]>([]);
const historyPage = ref(1);
const historyTotal = ref(0);
const historyFilters = ref<FilterGroup>({ mode: "and", conditions: [] });
const historyLoading = ref(false);
const detailLoading = ref(false);
const selectedRecord = ref<DebugHistoryDetail | null>(null);
const historyOpen = ref(false);
const historyDialog = ref<HTMLElement | null>(null);
const deleteTarget = ref<DebugHistoryItem | null>(null);
const deleting = ref(false);
const options = computed(() => source.value === "custom" ? [] : source.value === "access"
  ? models.value.filter((model) => model.model_type === "llm" && model.status === 1)
    .map((model) => ({ value: model.id, label: `${model.access_model_code} (${model.provider_model_name})` }))
  : aggregates.value.filter((model) => model.model_type === "llm" && model.status === 1)
    .map((model) => ({ value: model.id, label: model.public_model_name })));

function errorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : error instanceof Error ? error.message : "调试请求失败";
}

async function loadHistory(showLatest = false) {
  if (!isAdmin.value || !historyOpen.value) return;
  historyLoading.value = true;
  try {
    if (showLatest) historyPage.value = 1;
    const page = await listDebugHistory(historyPage.value, 20, historyFilters.value);
    if (!historyOpen.value) return;
    historyItems.value = page.items;
    historyTotal.value = page.total;
  } catch (error) {
    showToast("error", errorMessage(error));
  } finally {
    historyLoading.value = false;
  }
}

async function viewRecord(id: number) {
  detailLoading.value = true;
  try {
    const record = await getDebugHistory(id);
    if (historyOpen.value) selectedRecord.value = record;
  } catch (error) {
    showToast("error", errorMessage(error));
  } finally {
    detailLoading.value = false;
  }
}

function changeHistoryPage(page: number) {
  if (page < 1 || page > Math.ceil(historyTotal.value / 20)) return;
  historyPage.value = page;
  void loadHistory();
}

async function openHistory() {
  historyOpen.value = true;
  selectedRecord.value = null;
  await nextTick();
  historyDialog.value?.focus();
  void loadHistory(true);
}

function closeHistory() {
  if (deleteTarget.value || deleting.value) return;
  historyOpen.value = false;
  selectedRecord.value = null;
}

function onHistoryKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && historyOpen.value) {
    if (deleteTarget.value) deleteTarget.value = null;
    else closeHistory();
  }
}

async function confirmDelete() {
  if (!deleteTarget.value || deleting.value) return;
  deleting.value = true;
  try {
    const id = deleteTarget.value.id;
    await deleteDebugHistory(id);
    if (selectedRecord.value?.id === id) selectedRecord.value = null;
    deleteTarget.value = null;
    showToast("success", "调试记录已删除");
    await loadHistory();
    if (!historyItems.value.length && historyPage.value > 1) {
      historyPage.value--;
      await loadHistory();
    }
  } catch (error) {
    showToast("error", errorMessage(error));
  } finally {
    deleting.value = false;
  }
}

async function load() {
  loading.value = true;
  try {
    const [first, aggregatePage] = await Promise.all([
      listAccessModels({ page: 1, page_size: 100 }), listAggregates(),
    ]);
    const all = [...first.items];
    for (let page = 2; all.length < first.total; page++) {
      const next = await listAccessModels({ page, page_size: 100 });
      if (!next.items.length) break;
      all.push(...next.items);
    }
    models.value = all;
    aggregates.value = aggregatePage.items;
    if (source.value !== "custom") modelId.value = options.value[0]?.value ?? null;
  } catch (error) {
    showToast("error", errorMessage(error));
  } finally {
    loading.value = false;
  }
}

function resetConversation() {
  messages.value = [];
  result.value = null;
  rawResponse.value = "";
  rawMetadata.value = null;
  streamingAnswer.value = "";
}

function optionalNumber(value: number | null): number | null {
  return value === null || String(value) === "" ? null : value;
}

watch(source, () => {
  if (source.value !== "custom") customApiKey.value = "";
  modelId.value = options.value[0]?.value ?? null;
  resetConversation();
});
watch(modelId, () => resetConversation());
watch([customProtocol, customBaseUrl, customModelName], () => resetConversation());

function selectedAccessModel(): AccessModelItem | undefined {
  if (source.value === "access") return models.value.find((item) => item.id === modelId.value);
  const aggregate = aggregates.value.find((item) => item.id === modelId.value);
  return models.value.find((item) => item.id === aggregate?.routing_model_ids[0]);
}

async function generateTemplate() {
  if (busy.value) return;
  const model = selectedAccessModel();
  const currentSource = source.value;
  const currentModel = modelId.value;
  const previousBody = rawBody.value;
  let protocol: string = source.value === "custom" ? customProtocol.value : "openai_compatible";
  if (model?.protocol_id) {
    try {
      const protocols = await listProtocols(model.provider_id);
      protocol = protocols.find((item) => item.id === model.protocol_id)?.protocol_type ?? protocol;
    } catch (error) {
      showToast("error", errorMessage(error));
      return;
    }
  }
  if (source.value !== currentSource || modelId.value !== currentModel || rawBody.value !== previousBody) return;
  const name = source.value === "custom" ? customModelName.value.trim() : model?.provider_model_name ?? "";
  const question = draft.value.trim() || "你好，请介绍一下自己";
  const system = systemPrompt.value.trim();
  let body: Record<string, unknown>;
  if (protocol === "gemini") {
    body = { contents: [{ role: "user", parts: [{ text: question }] }] };
    if (system) body.systemInstruction = { parts: [{ text: system }] };
    body.generationConfig = {
      temperature: optionalNumber(temperature.value), topP: optionalNumber(topP.value),
      maxOutputTokens: optionalNumber(maxTokens.value),
    };
  } else if (protocol === "claude" || protocol === "anthropic") {
    body = { model: name, messages: [{ role: "user", content: question }],
      max_tokens: optionalNumber(maxTokens.value) ?? 1024 };
    if (system) body.system = system;
    if (optionalNumber(temperature.value) !== null) body.temperature = optionalNumber(temperature.value);
  } else {
    body = { model: name, messages: [
      ...(system ? [{ role: "system", content: system }] : []),
      { role: "user", content: question },
    ], temperature: optionalNumber(temperature.value), top_p: optionalNumber(topP.value),
    max_tokens: optionalNumber(maxTokens.value) };
  }
  rawBody.value = JSON.stringify(body, null, 2);
}

watch(mode, (next) => {
  if (next === "raw" && !rawBody.value) void generateTemplate();
});

function connection(): Pick<ChatRequest, "source" | "model_id" | "custom_protocol" | "custom_base_url" | "custom_model_name" | "custom_api_key"> {
  return {
    source: source.value, model_id: source.value === "custom" ? null : modelId.value,
    ...(source.value === "custom" ? {
      custom_protocol: customProtocol.value, custom_base_url: customBaseUrl.value.trim(),
      custom_model_name: customModelName.value.trim(), custom_api_key: customApiKey.value.trim() || null,
    } : {}),
  };
}

const canSend = computed(() => source.value === "custom"
  ? Boolean(customBaseUrl.value.trim() && customModelName.value.trim()) : Boolean(modelId.value));

function makeChatRequest(text: string): ChatRequest {
  const stops = stopText.value.split("\n").map((value) => value.trim()).filter(Boolean);
  if (stops.length > 4 || stops.some((value) => value.length > 128)) {
    throw new Error("最多填写 4 条停止词，每条不超过 128 字符");
  }
  if (useHistory.value && (!Number.isInteger(historyRounds.value) || historyRounds.value < 1 || historyRounds.value > 50)) {
    throw new Error("携带轮数须为 1 至 50 的整数");
  }
  const previous = useHistory.value ? messages.value.slice(-historyRounds.value * 2) : [];
  return {
    ...connection(), messages: [...previous, { role: "user", content: text }],
    system_prompt: systemPrompt.value, temperature: optionalNumber(temperature.value),
    top_p: optionalNumber(topP.value), max_tokens: optionalNumber(maxTokens.value), stop: stops,
  };
}

function parseStreamFrame(frame: string, protocol: string): { text: string; usage: ChatResult["usage"] | null } {
  const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart()).join("\n");
  if (!data || data === "[DONE]") return { text: "", usage: null };
  if (frame.includes("event: playground_error")) throw new Error("上游流式连接中断");
  try {
    const value = JSON.parse(data) as Record<string, any>;
    if (value.error) throw new Error(typeof value.error.message === "string" ? value.error.message : "上游流式响应错误");
    if (protocol === "gemini") {
      const text = value.candidates?.[0]?.content?.parts?.map((part: { text?: string }) => part.text ?? "").join("") ?? "";
      const usage = value.usageMetadata;
      return { text, usage: usage ? { input_tokens: usage.promptTokenCount ?? null,
        output_tokens: usage.candidatesTokenCount ?? null, total_tokens: usage.totalTokenCount ?? null } : null };
    }
    if (protocol === "claude" || protocol === "anthropic") {
      const usage = value.message?.usage ?? value.usage;
      return { text: value.delta?.text ?? "",
        usage: usage ? { input_tokens: usage.input_tokens ?? null,
          output_tokens: usage.output_tokens ?? null, total_tokens: null } : null };
    }
    const usage = value.usage;
    return { text: value.choices?.[0]?.delta?.content ?? "",
      usage: usage ? { input_tokens: usage.prompt_tokens ?? null,
        output_tokens: usage.completion_tokens ?? null, total_tokens: usage.total_tokens ?? null } : null };
  } catch (error) {
    if (error instanceof SyntaxError) return { text: "", usage: null };
    throw error;
  }
}

async function send() {
  const text = draft.value.trim();
  if (!isAdmin.value || busy.value || !canSend.value || !text) return;
  busy.value = true;
  try {
    const request = makeChatRequest(text);
    let response: ChatResult;
    if (streaming.value) {
      rawResponse.value = "";
      streamingAnswer.value = "";
      const started = performance.now();
      controller.value = new AbortController();
      let frameBuffer = "";
      let usage: ChatResult["usage"] = { input_tokens: null, output_tokens: null, total_tokens: null };
      const metadata = await executeDebug("chat/stream", request, (chunk, info) => {
        rawResponse.value += chunk;
        frameBuffer += chunk;
        const frames = frameBuffer.split(/\r?\n\r?\n/);
        frameBuffer = frames.pop() ?? "";
        for (const frame of frames) {
          const parsed = parseStreamFrame(frame, info.protocol);
          streamingAnswer.value += parsed.text;
          if (parsed.usage) usage = { ...usage, ...Object.fromEntries(
            Object.entries(parsed.usage).filter(([, value]) => value !== null),
          ) };
        }
      }, controller.value.signal);
      rawMetadata.value = metadata;
      if (!streamingAnswer.value.trim()) throw new Error("流式响应中没有可用的文本内容，请查看原始流");
      response = { content: streamingAnswer.value, access_model_code: metadata.model,
        protocol: metadata.protocol, latency_ms: Math.round(performance.now() - started), usage };
    } else {
      response = await debugChat(request);
      rawResponse.value = "";
      rawMetadata.value = null;
    }
    messages.value.push({ role: "user", content: text }, { role: "assistant", content: response.content });
    result.value = response;
    draft.value = "";
  } catch (error) {
    showToast("error", error instanceof DOMException && error.name === "AbortError" ? "已停止生成" : errorMessage(error));
  } finally {
    controller.value = null;
    busy.value = false;
    void loadHistory(true);
  }
}

function onDraftKeydown(event: KeyboardEvent) {
  if (event.ctrlKey && event.key === "Enter" && !event.isComposing) {
    event.preventDefault();
    void send();
  }
}

function parseObject(text: string, label: string): Record<string, unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error(`${label}必须是有效的 JSON 对象`);
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label}必须是 JSON 对象`);
  }
  return value as Record<string, unknown>;
}

async function sendRaw() {
  if (!isAdmin.value || busy.value || !canSend.value) return;
  try {
    const body = parseObject(rawBody.value, "请求体 Body");
    const raw = parseObject(rawHeaders.value, "请求头 Header");
    if (Object.values(raw).some((value) => typeof value !== "string")) {
      throw new Error("请求头 Header 的值必须是字符串");
    }
    const payload: RawRequest = { ...connection(), body, headers: raw as Record<string, string>,
      stream: streaming.value };
    rawResponse.value = "";
    rawMetadata.value = null;
    busy.value = true;
    controller.value = new AbortController();
    rawMetadata.value = await executeDebug("raw", payload, (chunk) => {
      rawResponse.value += chunk;
    }, controller.value.signal);
  } catch (error) {
    showToast("error", error instanceof DOMException && error.name === "AbortError" ? "已停止请求" : errorMessage(error));
  } finally {
    controller.value = null;
    busy.value = false;
    void loadHistory(true);
  }
}

function removeTurn(index: number) {
  messages.value.splice(index, 2);
  result.value = null;
}

onMounted(() => {
  void load();
  window.addEventListener("keydown", onHistoryKeydown);
});
onUnmounted(() => {
  controller.value?.abort();
  window.removeEventListener("keydown", onHistoryKeydown);
});
</script>

<template>
  <div class="page-stack playground">
    <div class="page-card playground-header">
      <div><h2>在线调试</h2><p>支持多轮对话或直接编辑请求 Body/Header，并查看实时原始流。</p></div>
      <div class="header-actions">
        <button v-if="mode === 'conversation'" type="button" class="secondary" :disabled="busy || !messages.length" @click="resetConversation">清空对话</button>
        <button v-if="isAdmin" type="button" class="secondary history-trigger" aria-label="历史调试记录" title="历史调试记录" @click="openHistory">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M3 12a9 9 0 1 0 2.5-6.2M3 4v4h4M12 7v5l3 2" />
          </svg>
        </button>
      </div>
    </div>
    <div class="playground-grid">
      <section class="page-card settings">
        <label>调试模式<AppSelect v-model="mode" :disabled="busy" :options="[
          { label: '多轮对话', value: 'conversation' }, { label: '原始请求', value: 'raw' },
        ]" /></label>
        <label class="check"><input v-model="streaming" :disabled="busy" type="checkbox" />流式响应</label>
        <h3>模型与参数</h3>
        <label>模型来源<AppSelect v-model="source" :disabled="busy" :options="[
          { label: '模型管理', value: 'access' }, { label: '聚合模型', value: 'aggregate' },
          { label: '自定义模型', value: 'custom' },
        ]" /></label>
        <template v-if="source === 'custom'">
          <label>接口协议<AppSelect v-model="customProtocol" :disabled="busy" :options="[
            { label: 'OpenAI 兼容', value: 'openai_compatible' },
            { label: 'OpenAI', value: 'openai' },
            { label: 'Claude', value: 'claude' },
            { label: 'Gemini', value: 'gemini' },
          ]" /></label>
          <label>Base URL<input v-model.trim="customBaseUrl" :disabled="busy" type="url"
            placeholder="https://api.example.com/v1" maxlength="2048" /></label>
          <label>模型名称（Model Name）<input v-model.trim="customModelName" :disabled="busy"
            placeholder="填写上游模型名称" maxlength="128" /></label>
          <label>API Key（可选）<input v-model="customApiKey" :disabled="busy" type="password"
            autocomplete="off" spellcheck="false" placeholder="仅用于本次页面调试" maxlength="4096" /></label>
          <p class="hint">仅支持公网 HTTPS 443 地址。自定义连接不会保存到模型管理；API Key 离开自定义模式后会清空。</p>
        </template>
        <label v-else>调试模型<AppSelect v-model="modelId" :disabled="busy || loading" :options="options"
          placeholder="选择已启用的 LLM 模型" /></label>
        <p v-if="source !== 'custom' && !loading && !options.length" class="notice">暂无可用的 LLM 模型，请先在对应管理页面配置并启用模型。</p>
        <template v-if="mode === 'conversation'">
          <label>系统提示词<textarea v-model="systemPrompt" :disabled="busy" rows="4" maxlength="32000" placeholder="设定助手角色和回答要求（可选）" /></label>
          <div class="settings-pair">
            <label>温度 (0-2)<input v-model.number="temperature" :disabled="busy" type="number" min="0" max="2" step="0.1" /></label>
            <label>Top P (0-1)<input v-model.number="topP" :disabled="busy" type="number" min="0.01" max="1" step="0.05" /></label>
          </div>
          <label>最大输出 Token<input v-model.number="maxTokens" :disabled="busy" type="number" min="1" max="2147483647" step="1" /></label>
          <label>停止词（每行一个，最多 4 个）<textarea v-model="stopText" :disabled="busy" rows="2" placeholder="可选" /></label>
          <h3>多轮对话</h3>
          <label class="check"><input v-model="useHistory" :disabled="busy" type="checkbox" />携带历史消息</label>
          <label>携带最近轮数<input v-model.number="historyRounds" :disabled="busy || !useHistory" type="number" min="1" max="50" step="1" /></label>
          <p class="hint">历史仅保留在当前页面。修改或移除轮次后，下次发送会使用更新后的消息。</p>
        </template>
        <p v-else class="hint">原始模式以右侧 JSON 请求体为准。流式开关会覆盖请求体中的 stream 字段；Gemini 使用流式接口路径。</p>
        <p class="hint">聚合模型使用已配置的候选路由；最低延迟策略目前没有实时延迟数据，会按候选顺序选择可用模型。</p>
      </section>
      <section v-if="mode === 'conversation'" class="page-card conversation">
        <h3>对话记录</h3>
        <div class="turns" :class="{ 'turns--empty': !messages.length }">
          <div v-if="!messages.length" class="empty">输入消息开始调试。每次发送后可继续追问。</div>
          <div v-for="(_, index) in messages.filter((message) => message.role === 'user')" :key="index" class="turn">
            <div class="turn-heading"><strong>第 {{ index + 1 }} 轮</strong>
              <button type="button" :disabled="busy" @click="removeTurn(index * 2)">移除</button></div>
            <label>用户消息<textarea v-model="messages[index * 2]!.content" :disabled="busy" rows="2" maxlength="32000" /></label>
            <label>模型回复<textarea v-model="messages[index * 2 + 1]!.content" :disabled="busy" rows="3" maxlength="32000" /></label>
          </div>
        </div>
        <div v-if="result" class="metrics">
          <span>实际接入：{{ result.access_model_code }}</span>
          <span>协议：{{ result.protocol }}</span>
          <span>耗时：{{ result.latency_ms }} ms</span>
          <span>输入 / 输出 / 总 Token：{{ result.usage.input_tokens ?? "-" }} / {{ result.usage.output_tokens ?? "-" }} / {{ result.usage.total_tokens ?? "-" }}</span>
        </div>
        <div v-if="busy && streaming && streamingAnswer" class="turn">
          <strong>模型正在回复</strong><p class="live-answer">{{ streamingAnswer }}</p>
        </div>
        <details v-if="streaming && (rawResponse || busy)" class="stream-panel" open>
          <summary>原始流式响应（实时）</summary>
          <pre aria-live="polite">{{ rawResponse || "等待上游响应..." }}</pre>
        </details>
        <form class="composer" @submit.prevent="send">
          <label for="playground-draft">输入消息</label>
          <div class="composer-input">
            <textarea id="playground-draft" v-model="draft" :disabled="busy || !isAdmin" rows="4" maxlength="32000"
              placeholder="输入本轮问题..." @keydown="onDraftKeydown" />
            <button class="page-action send-button" type="submit" aria-label="发送消息" title="发送消息 (Ctrl + Enter)"
              :disabled="busy || !isAdmin || !draft.trim() || !canSend">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="m21 3-8.4 18-2.9-7.7L2 10.4 21 3Z" />
                <path d="m9.7 13.3 5.4-5.4" />
              </svg>
            </button>
          </div>
          <div class="composer-actions">
            <span>{{ !isAdmin ? "仅平台管理员可发起上游调试请求。" : busy ? "正在接收响应..." : "Ctrl + Enter 发送" }}</span>
            <button v-if="busy && streaming" class="secondary" type="button" @click="controller?.abort()">停止生成</button>
          </div>
        </form>
      </section>
      <section v-else class="page-card conversation raw-editor">
        <div class="playground-header">
          <div><h3>原始请求</h3><p>直接编辑发送给上游的 JSON Body 和附加 Header。</p></div>
          <button class="secondary" type="button" :disabled="busy" @click="generateTemplate">生成请求体示例</button>
        </div>
        <label>请求体 Body（JSON 对象）
          <textarea v-model="rawBody" class="code-editor" :disabled="busy" rows="16" spellcheck="false" placeholder='{"model":"...","messages":[{"role":"user","content":"你好"}]}' />
        </label>
        <label>附加请求头 Header（JSON 对象）
          <textarea v-model="rawHeaders" class="code-editor" :disabled="busy" rows="5" spellcheck="false" placeholder='{"x-custom-header":"value"}' />
        </label>
        <p class="hint">已配置模型的认证头由服务端添加，不会回填在此处；同名自定义 Header 会覆盖它。禁止发送 Host、Content-Length 等连接控制头。</p>
        <div class="composer-actions">
          <span v-if="!isAdmin">仅平台管理员可发起上游调试请求。</span>
          <button v-if="busy" class="secondary" type="button" @click="controller?.abort()">停止请求</button>
          <button v-else class="page-action" type="button" :disabled="!isAdmin || !canSend || !rawBody.trim()" @click="sendRaw">发送原始请求</button>
        </div>
        <div v-if="rawMetadata" class="metrics">
          <span>实际接入：{{ rawMetadata.model }}</span><span>协议：{{ rawMetadata.protocol }}</span>
          <span>首包耗时：{{ rawMetadata.latencyMs }} ms</span>
        </div>
        <details v-if="streaming && (rawResponse || busy)" class="stream-panel" open>
          <summary>原始流式响应（实时）</summary>
          <pre aria-live="polite">{{ rawResponse || "等待上游响应..." }}</pre>
        </details>
        <div v-else-if="rawResponse || busy" class="stream-panel">
          <h3>上游原始响应</h3>
          <pre aria-live="polite">{{ rawResponse || "等待上游响应..." }}</pre>
        </div>
      </section>
    </div>
    <Teleport to="body">
      <div v-if="historyOpen" class="app-modal-overlay" v-backdrop-close="closeHistory">
        <section ref="historyDialog" class="app-modal-panel history-dialog" role="dialog" aria-modal="true" aria-label="历史调试记录" tabindex="-1">
          <header class="history-dialog__header">
            <div><h2>{{ selectedRecord ? `调试详情 #${selectedRecord.id}` : "历史调试记录" }}</h2>
              <p>{{ selectedRecord ? `${selectedRecord.model_code} · ${selectedRecord.protocol} · ${selectedRecord.stream ? "流式" : "非流式"}` : "仅展示当前账号记录，敏感请求头已脱敏。" }}</p></div>
            <AppFilterTags v-if="!selectedRecord" :fields="listFilterFields.history" :model-value="historyFilters" @apply="historyFilters = $event; loadHistory(true)" />
            <div class="header-actions">
              <button v-if="selectedRecord" type="button" class="secondary" @click="selectedRecord = null">返回列表</button>
              <button v-else type="button" class="secondary" :disabled="historyLoading" @click="loadHistory()">刷新</button>
              <AppListFilter v-if="!selectedRecord" :fields="listFilterFields.history" :model-value="historyFilters" hide-tags @apply="historyFilters = $event; loadHistory(true)" />
              <button class="secondary close-button" type="button" aria-label="关闭历史调试记录" @click="closeHistory">×</button>
            </div>
          </header>
          <div class="history-dialog__body">
            <template v-if="selectedRecord">
              <div class="metrics">
                <span>状态：{{ selectedRecord.http_status ?? "进行中" }}</span>
                <span>耗时：{{ selectedRecord.latency_ms === null ? "-" : `${selectedRecord.latency_ms} ms` }}</span>
                <span>来源：{{ selectedRecord.source }}</span>
              </div>
              <p v-if="selectedRecord.truncated" class="notice">原始返回超过 256 KB，记录仅保留前 256 KB；解析结果可能不完整。</p>
              <div class="history-section">
                <h3>解析后的内容</h3>
                <pre v-if="selectedRecord.parsed_content" class="parsed-content">{{ selectedRecord.parsed_content }}</pre>
                <p v-else class="hint">没有可解析的文本内容，请查看下方原始返回结果。</p>
              </div>
              <div class="history-section"><h3>实际发送的原始请求</h3>
                <label>请求地址<pre>{{ selectedRecord.request_url }}</pre></label>
                <label>请求 Header（敏感值已脱敏）<pre>{{ JSON.stringify(selectedRecord.request_headers, null, 2) }}</pre></label>
                <label>请求 Body<pre>{{ JSON.stringify(selectedRecord.request_body, null, 2) }}</pre></label>
              </div>
              <div class="history-section"><h3>{{ selectedRecord.stream ? "原始流式返回（SSE）" : "原始返回结果" }}</h3>
                <pre>{{ selectedRecord.response_body ?? "暂无返回内容" }}</pre>
              </div>
            </template>
            <template v-else>
              <div v-if="historyLoading && !historyItems.length" class="empty">正在加载...</div>
              <div v-else-if="!historyItems.length" class="empty">暂无调试记录</div>
              <div v-else class="history-table-wrap">
                <table class="history-table">
                  <thead><tr><th>时间</th><th>模型</th><th>模式</th><th>状态</th><th>耗时</th><th>操作</th></tr></thead>
                  <tbody><tr v-for="item in historyItems" :key="item.id">
                    <td>{{ item.created_at ? new Date(item.created_at).toLocaleString() : "-" }}</td>
                    <td>{{ item.model_code }} <small>({{ item.source }})</small></td>
                    <td>{{ item.mode === "conversation" ? "多轮对话" : "原始请求" }}{{ item.stream ? " · 流式" : "" }}</td>
                    <td>{{ item.http_status ?? "进行中" }}</td>
                    <td>{{ item.latency_ms === null ? "-" : `${item.latency_ms} ms` }}</td>
                    <td class="history-actions">
                      <button class="text-action" type="button" :disabled="detailLoading" @click="viewRecord(item.id)">查看详情</button>
                      <button class="text-action text-action--danger" type="button" :disabled="item.http_status === null || deleting" @click="deleteTarget = item">删除</button>
                    </td>
                  </tr></tbody>
                </table>
              </div>
              <div v-if="historyTotal > 20" class="history-pages">
                <span>共 {{ historyTotal }} 条 · 第 {{ historyPage }} / {{ Math.ceil(historyTotal / 20) }} 页</span>
                <button class="secondary" type="button" :disabled="historyLoading || historyPage === 1" @click="changeHistoryPage(historyPage - 1)">上一页</button>
                <button class="secondary" type="button" :disabled="historyLoading || historyPage * 20 >= historyTotal" @click="changeHistoryPage(historyPage + 1)">下一页</button>
              </div>
            </template>
          </div>
        </section>
      </div>
      <div v-if="deleteTarget" class="app-modal-overlay app-modal-overlay--confirmation" v-backdrop-close="() => { !deleting && (deleteTarget = null) }">
        <div class="app-modal-panel history-confirm" role="alertdialog" aria-modal="true" aria-label="删除调试记录">
          <h3>删除调试记录</h3>
          <p>确定删除「{{ deleteTarget.model_code }}」的这条调试记录吗？删除后无法恢复。</p>
          <div class="header-actions">
            <button class="secondary" type="button" :disabled="deleting" @click="deleteTarget = null">取消</button>
            <button class="danger-button" type="button" :disabled="deleting" @click="confirmDelete">{{ deleting ? "删除中..." : "确定删除" }}</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.playground-header,.composer-actions,.turn-heading{display:flex;align-items:center;justify-content:space-between;gap:16px}
h2,h3{margin:0 0 12px}h2{font-size:20px}h3{font-size:16px}p{margin:0;color:#64748b;font-size:13px;line-height:1.6}
.playground-grid{display:grid;grid-template-columns:minmax(260px,340px) minmax(0,1fr);gap:20px;align-items:start}
.settings{display:grid;gap:16px}.settings h3:not(:first-child){margin-top:8px}
label{display:grid;gap:7px;color:#475569;font-size:13px}.check{display:flex;align-items:center;gap:8px}
input:not([type="checkbox"]),textarea{width:100%;min-width:0;padding:9px 11px;border:1px solid #d8e1e9;border-radius:8px;background:white;color:#182d37;font:inherit}
textarea{resize:vertical;line-height:1.5}.settings-pair{display:grid;grid-template-columns:1fr 1fr;gap:12px;min-width:0}
.notice{color:#b45309}.hint{font-size:12px}.conversation{min-width:0}
.conversation:not(.raw-editor){display:flex;flex-direction:column;min-height:calc(100dvh - 180px)}
.turns{display:grid;gap:16px;min-height:180px;max-height:65vh;overflow:auto;margin:16px 0}
.turns--empty{display:flex;flex:1;max-height:none}
.empty{padding:50px 16px;text-align:center;color:#64748b;background:#f7fafb;border-radius:10px}
.turns--empty .empty{display:grid;place-items:center;flex:1}
.turn{display:grid;gap:12px;padding:16px;border:1px solid #e2e8f0;border-radius:10px}
.turn-heading strong{color:#173943}.turn-heading button{border:0;background:none;color:#c93636;cursor:pointer}
.metrics{display:flex;flex-wrap:wrap;gap:8px 18px;padding:12px;background:#f0f8f7;border-radius:8px;color:#176c61;font-size:12px}
.composer{display:grid;gap:10px;padding-top:18px;border-top:1px solid #e2e8f0}
.composer-input{position:relative}
.composer-input textarea{display:block;padding-bottom:52px}
.composer-input .send-button{position:absolute;right:12px;bottom:12px;display:grid;place-items:center;width:36px;height:36px;padding:8px;border-radius:9px;cursor:pointer}
.send-button svg{width:20px;height:20px}
.composer-actions span{color:#b45309;font-size:12px}.secondary{padding:8px 12px;border:1px solid #d8e1e9;border-radius:8px;background:white;color:#176c61;cursor:pointer}
.raw-editor{display:grid;gap:16px}.raw-editor h3{margin:0}.code-editor,.stream-panel pre{font-family:Consolas,"Courier New",monospace;font-size:12px;line-height:1.6}
.stream-panel{min-width:0;padding-top:16px}.stream-panel pre{max-height:420px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#102831;color:#e2f5f0;padding:16px;border-radius:8px}
.stream-panel summary{width:fit-content;margin-bottom:12px;color:#173943;font-size:16px;font-weight:650;cursor:pointer}
.stream-panel summary:focus-visible{outline:2px solid #70dbc9;outline-offset:3px}
.live-answer{white-space:pre-wrap;overflow-wrap:anywhere;color:#173943}
.header-actions{display:flex;align-items:center;justify-content:flex-end;flex-wrap:wrap;gap:10px;flex-shrink:1;min-width:0;max-width:100%}
.history-trigger{display:grid;place-items:center;width:38px;height:38px;padding:8px}
.history-trigger svg{width:20px;height:20px}
.history-dialog{width:90vw;height:90dvh;max-height:90dvh;display:flex;flex-direction:column;overflow:hidden}
.history-dialog__header{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:20px 24px;border-bottom:1px solid #e2e8f0}
.history-dialog__header h2{margin:0 0 6px;font-size:18px}
.close-button{font-size:24px;line-height:1;padding:4px 10px}
.history-dialog__body{display:flex;flex-direction:column;gap:16px;min-height:0;flex:1;overflow:auto;padding:20px 24px}
.history-dialog__body .empty{flex:1;display:grid;place-items:center}
.history-table-wrap{overflow:auto;flex:1;min-height:0}
.history-section{display:grid;gap:12px}.history-section h3{margin:0}
.history-section pre{margin:0;max-height:320px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#f6f9fa;border:1px solid #e2e8f0;border-radius:8px;padding:12px;color:#173943;font:12px/1.6 Consolas,"Courier New",monospace}
.history-section pre.parsed-content{max-height:none;min-height:100px;background:#f0f8f7;font-family:inherit;font-size:14px;line-height:1.7}
.history-table{width:100%;border-collapse:collapse;text-align:left;white-space:nowrap}
.history-table th,.history-table td{padding:12px;border-bottom:1px solid #e2e8f0;font-size:13px}
.history-table th{position:sticky;top:0;background:#fff}.history-table th,.history-table small{color:#64748b}
.history-actions{display:flex;gap:14px}.text-action{border:0;background:none;color:#146d70;cursor:pointer}.text-action--danger{color:#c93636}
.history-pages{display:flex;justify-content:flex-end;align-items:center;gap:10px;color:#64748b;font-size:12px}
.history-confirm{width:min(440px,100%);padding:24px}.history-confirm h3{margin:0 0 14px}
.history-confirm p{margin-bottom:24px}.danger-button{padding:8px 14px;border:1px solid #c93636;border-radius:8px;background:#c93636;color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
@media(max-width:900px){.playground-grid{grid-template-columns:1fr}.conversation:not(.raw-editor){min-height:65dvh}.turns{max-height:none}.history-dialog__header{padding:16px}.history-dialog__body{padding:16px}}
@media(max-width:560px){.playground-header{flex-wrap:wrap}.history-dialog__header{align-items:flex-start}.history-dialog__header .header-actions{flex-wrap:wrap}}
</style>
