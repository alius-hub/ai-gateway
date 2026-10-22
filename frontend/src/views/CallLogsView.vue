<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppListFilter from "@/AppListFilter.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import AppPagination from "@/AppPagination.vue";
import { getCallImage, getCallLog, getCallRaw, listCallLogs, type CallLog, type CallLogDetail, type RawCallFile, type RawCallPreview } from "@/api/logs";
import { isAxiosError } from "axios";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
import { showToast } from "@/utils/toast";

const items = ref<CallLog[]>([]);
const route = useRoute();
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const query = ref("");
const activeQuery = ref("");
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
const loading = ref(false);
const selected = ref<CallLogDetail | null>(null);
const detailLoading = ref(false);
const rawFiles: { name: RawCallFile; label: string }[] = [
  { name: "request.bin", label: "客户端请求" },
  { name: "upstream_request.bin", label: "上游请求" },
  { name: "upstream_response.bin", label: "上游响应" },
  { name: "response.bin", label: "客户端响应" },
];
const activeFile = ref<RawCallFile>("upstream_response.bin");
const rawPreview = ref<RawCallPreview | null>(null);
const rawLoading = ref(false);
const rawError = ref("");
const pretty = ref(true);
let rawGeneration = 0;
const rawText = computed(() => {
  const text = rawPreview.value?.text ?? "";
  if (!pretty.value) return text;
  try { return JSON.stringify(JSON.parse(text), null, 2); } catch { return text; }
});
const headerGroups = computed(() => [
  { label: "客户端请求头", value: selected.value?.archive?.manifest?.request_headers },
  { label: "上游请求头", value: selected.value?.archive?.manifest?.upstream_request_headers },
  { label: "上游响应头", value: selected.value?.archive?.manifest?.upstream_response_headers },
  { label: "客户端响应头", value: selected.value?.archive?.manifest?.response_headers },
]);

async function loadRaw(filename: RawCallFile = activeFile.value) {
  if (!selected.value) return;
  const current = ++rawGeneration;
  const requestId = selected.value.request_id;
  activeFile.value = filename;
  rawPreview.value = null;
  rawError.value = "";
  rawLoading.value = true;
  try {
    const preview = await getCallRaw(requestId, filename);
    if (current === rawGeneration) rawPreview.value = preview;
  } catch (error) {
    if (current !== rawGeneration) return;
    const detail = isAxiosError(error) ? error.response?.data?.detail : undefined;
    rawError.value = typeof detail === "string" ? detail : "读取原始内容失败，请重试";
  } finally {
    if (current === rawGeneration) rawLoading.value = false;
  }
}
const previews = ref<Record<number, string>>({});
let generation = 0;
let detailGeneration = 0;


async function load() {
  const current = ++generation;
  items.value = [];
  loading.value = true;
  try {
    const result = await listCallLogs(page.value, activeQuery.value, filters.value, pageSize.value);
    if (current !== generation) return;
    items.value = result.items;
    total.value = result.total;
  } catch {
    if (current === generation) showToast("error", "加载调用日志失败");
  } finally {
    if (current === generation) loading.value = false;
  }
}

function search() {
  activeQuery.value = query.value.trim();
  page.value = 1;
  void load();
}

function applyFilters(value: FilterGroup) {
  filters.value = value;
  page.value = 1;
  void load();
}

function changePageSize(next: number) {
  pageSize.value = next;
  page.value = 1;
  void load();
}

async function openDetail(requestId: string) {
  const current = ++detailGeneration;
  rawGeneration++;
  rawPreview.value = null;
  rawError.value = "";
  rawLoading.value = false;
  clearPreviews();
  detailLoading.value = true;
  selected.value = null;
  try {
    const detail = await getCallLog(requestId);
    if (current !== detailGeneration) return;
    selected.value = detail;
    detailLoading.value = false;
    if (detail.archive?.status === "stored") void loadRaw("upstream_response.bin");
    for (const image of detail.images) {
      if (image.kind === "url") continue;
      try {
        const blob = await getCallImage(requestId, image.index);
        if (current !== detailGeneration) return;
        previews.value[image.index] = URL.createObjectURL(blob);
      } catch {
        // Other previews remain available when one image is invalid or too large.
      }
    }
  } catch {
    if (current === detailGeneration) showToast("error", "加载日志详情失败");
  } finally {
    if (current === detailGeneration) detailLoading.value = false;
  }
}

function clearPreviews() {
  for (const url of Object.values(previews.value)) URL.revokeObjectURL(url);
  previews.value = {};
}

function closeDetail() {
  detailGeneration++;
  rawGeneration++;
  rawPreview.value = null;
  rawLoading.value = false;
  rawError.value = "";
  selected.value = null;
  detailLoading.value = false;
  clearPreviews();
}

watch(() => route.query.filters, (raw) => {
  try {
    const parsed = typeof raw === "string" ? JSON.parse(raw) as FilterGroup : null;
    filters.value = parsed?.mode === "and" || parsed?.mode === "or"
      ? parsed.conditions?.length <= 8 && parsed.conditions.every((condition) =>
        listFilterFields.logs.some((field) => field.key === condition.field))
        ? parsed : { mode: "and", conditions: [] }
      : { mode: "and", conditions: [] };
  } catch {
    filters.value = { mode: "and", conditions: [] };
  }
  page.value = 1;
  void load();
}, { immediate: true });
onUnmounted(() => {
  generation++;
  items.value = [];
  closeDetail();
});
</script>

<template>
  <section class="page-stack call-logs">
    <div class="page-card call-header">
      <div>
        <h2>调用日志</h2>
        <p>按请求 ID 查询调用、用量及原始归档。原始请求头可能包含凭据，请仅在受信任环境中下载。</p>
      </div>
      <AppFilterTags :fields="listFilterFields.logs" :model-value="filters" @apply="applyFilters" />
      <div class="app-list-toolbar-actions">
        <form class="call-search" @submit.prevent="search">
          <input v-model="query" placeholder="输入请求 ID" aria-label="请求 ID" />
          <button type="submit">查询</button>
        </form>
        <AppListFilter :fields="listFilterFields.logs" :model-value="filters" hide-tags @apply="applyFilters" />
      </div>
    </div>
    <div class="page-card call-table-wrap">
      <table class="call-table">
        <thead><tr><th>时间</th><th>请求 ID</th><th>模型</th><th>API Key</th><th>接入模型 ID</th><th>来源 IP</th><th>状态</th><th>耗时</th><th title="输出 Token（含思考）÷ 总耗时（秒）">TPS (Token/s)</th><th>输入 / 输出 Token</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.request_id">
            <td>{{ new Date(item.created_at).toLocaleString() }}</td>
            <td class="request-id">{{ item.request_id }}</td>
            <td>{{ item.model }}</td>
            <td class="request-id" :title="item.api_key_snapshot ? `Key #${item.api_key_id} · 调用时的脱敏快照` : '历史日志未记录尾部，仅显示当前已存前缀'">{{ item.api_key_masked || (item.api_key_id ? `Key #${item.api_key_id}` : '—') }}</td>
            <td>{{ item.provider_model_id ?? "-" }}</td>
            <td>{{ item.requester_ip }}</td>
            <td>{{ item.http_status }}<span v-if="item.error_code"> · {{ item.error_code }}</span></td>
            <td>{{ item.latency_ms ?? "-" }} ms</td>
            <td>{{ item.tps == null ? '—' : item.tps.toFixed(2) }}</td>
            <td>{{ item.input_tokens ?? "-" }} / {{ item.output_tokens ?? "-" }}</td>
            <td><button type="button" @click="openDetail(item.request_id)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="11" class="empty">{{ loading ? "正在加载..." : "暂无调用日志" }}</td></tr>
        </tbody>
      </table>
      <AppPagination v-model="page" :total="total" :page-size="pageSize" :disabled="loading" @change="load" @update:page-size="changePageSize" />
    </div>
    <div v-if="selected || detailLoading" class="app-modal-overlay" v-backdrop-close="closeDetail">
      <div class="app-modal-panel call-detail" role="dialog" aria-modal="true" aria-label="调用日志详情">
        <header class="detail-heading"><div><span class="detail-eyebrow">请求追踪</span><h2>调用详情</h2></div><div class="detail-heading-actions"><span v-if="selected" class="status-badge" :class="{ failed: selected.http_status >= 400 }">HTTP {{ selected.http_status }}</span><button type="button" @click="closeDetail">关闭</button></div></header>
        <div class="detail-body">
        <p v-if="detailLoading">正在加载...</p>
        <template v-else-if="selected">
          <div class="request-overview"><span>请求 ID</span><code>{{ selected.request_id }}</code><span>{{ new Date(selected.created_at).toLocaleString() }}</span></div>
          <div class="metric-grid">
            <div><span>调用模型</span><strong>{{ selected.model }}</strong><small>接入模型 #{{ selected.provider_model_id ?? '-' }}</small></div>
            <div><span>总耗时</span><strong>{{ selected.latency_ms ?? '-' }} <small>ms</small></strong><small>上游状态 {{ selected.provider_status ?? '-' }}</small></div>
            <div><span>Token 总量</span><strong>{{ selected.total_tokens ?? '-' }}</strong><small>输入 {{ selected.input_tokens ?? '-' }} / 输出 {{ selected.output_tokens ?? '-' }}</small></div>
            <div><span>思考 / 非思考 Token</span><strong>{{ selected.reasoning_tokens ?? '-' }} / {{ selected.non_reasoning_tokens ?? '-' }}</strong><small>来源 {{ selected.requester_ip }}</small></div>
          </div>
          <div class="timing-strip"><span>TTFT <b>{{ selected.ttft_ms ?? '-' }} ms</b></span><span>TPOT <b>{{ selected.tpot_ms ?? '-' }} ms/token</b></span><span title="输出 Token（含思考）÷ 总耗时（秒）">TPS <b>{{ selected.tps == null ? '—' : selected.tps.toFixed(2) }} Token/s</b></span><span>接口 <b>{{ selected.endpoint }}</b></span></div>
          <p v-if="selected.error_code || selected.error_message" class="detail-error">{{ selected.error_code }} {{ selected.error_message }}</p>
          <template v-if="selected.images.length">
            <h3>请求图片</h3>
            <div class="image-list">
              <figure v-for="image in selected.images" :key="image.index">
                <img v-if="image.url || previews[image.index]"
                     :src="image.url || previews[image.index]" referrerpolicy="no-referrer"
                     alt="请求中的图片" loading="lazy" />
                <figcaption>
                  <a v-if="image.url" :href="image.url" target="_blank" rel="noopener noreferrer"
                     referrerpolicy="no-referrer">查看图片链接</a>
                  <span v-else>{{ previews[image.index] ? "内嵌图片" : "图片无法预览" }}</span>
                </figcaption>
              </figure>
            </div>
          </template>
          <p v-if="!selected.archive">原始内容归档未启用或尚未生成。</p>
          <p v-else-if="selected.archive.status === 'pending'">原始内容正在后台上传，稍后重新打开详情。</p>
          <p v-else-if="selected.archive.status === 'unavailable'">归档暂时不可查询，请检查对象存储连接。</p>
          <template v-else>
            <p v-if="!selected.archive.manifest?.capture_complete" class="warning">本次原始内容采集不完整。</p>
            <section class="raw-section">
              <div class="section-heading"><h3>原始请求与响应</h3><p>直接查看调用链路中的原始内容，对照上游与客户端响应。</p></div>
              <div class="raw-tabs" role="tablist" aria-label="原始内容类型"><button v-for="file in rawFiles" :key="file.name" type="button" role="tab" :aria-selected="activeFile === file.name" :class="{ active: activeFile === file.name }" @click="loadRaw(file.name)">{{ file.label }}</button></div>
              <div class="raw-viewer">
                <div class="raw-toolbar"><code>{{ activeFile }}</code><div><button type="button" @click="pretty = !pretty">{{ pretty ? '格式化' : '原文' }}</button><button type="button" :disabled="rawLoading" @click="loadRaw()">重新读取</button><a v-if="selected.archive.downloads?.[activeFile]" :href="selected.archive.downloads[activeFile]" target="_blank" rel="noopener noreferrer">下载完整文件</a></div></div>
                <p v-if="rawLoading" class="raw-state">正在读取原始内容...</p><p v-else-if="rawError" class="raw-state warning">{{ rawError }}</p>
                <template v-else-if="rawPreview"><p v-if="rawPreview.truncated" class="preview-limit">仅预览前 2 MB，完整内容请下载文件。</p><pre class="raw-code">{{ rawText || '（空文件）' }}</pre><div class="raw-footer">{{ rawPreview.size_bytes == null ? '' : `${rawPreview.size_bytes.toLocaleString()} 字节 · ` }}UTF-8 文本预览</div></template>
              </div>
              <details class="headers-section"><summary>请求与响应头</summary><div class="headers-grid"><section v-for="group in headerGroups" :key="group.label"><h4>{{ group.label }}</h4><pre>{{ JSON.stringify(group.value || [], null, 2) }}</pre></section></div></details>
              <details class="archive-downloads"><summary>全部归档文件</summary><div class="download-list"><a v-for="(url, name) in selected.archive.downloads" :key="name" :href="url" target="_blank" rel="noopener noreferrer">{{ name }}</a></div><p>下载链接生成后 60 秒有效，过期后请重新打开详情。</p></details>
            </section>
            <p v-for="image in selected.archive.manifest?.external_images" :key="image.url">
              外链图片：{{ image.url }} · {{ image.saved ? "已保存" : `未保存（${image.error}）` }}
            </p>
          </template>
        </template>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.call-header,.call-header header,.call-detail header,.call-pages{display:flex;justify-content:space-between;align-items:center;gap:12px}
.call-header{flex-wrap:wrap}
h2{margin:0 0 8px;font-size:20px}
p{color:#64748b;font-size:13px;line-height:1.6}
.call-search{display:flex;gap:8px;flex-wrap:wrap}
input{min-height:36px;padding:6px 10px;border:1px solid #d8e1e9;border-radius:8px;min-width:240px}
button{min-height:34px;padding:6px 12px;border:1px solid #d6e5e3;border-radius:9px;background:#f4faf8;color:#217c70;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
.call-table-wrap{overflow-x:auto;padding:0}
.call-table{width:100%;min-width:850px;border-collapse:collapse;text-align:left}
th,td{padding:13px 16px;border-bottom:1px solid #edf1f3;font-size:12px;white-space:nowrap}
th{background:#f7f9fa;color:#6d8090}
.request-id{font-family:monospace}
.empty{text-align:center;padding:36px}
.call-pages{justify-content:flex-end;padding:12px 16px}
.call-detail{box-sizing:border-box;width:80vw;height:90vh;height:90dvh;overflow:hidden;display:flex;flex-direction:column;padding:0;background:#f7f9fb}
.detail-heading{padding:20px 26px;background:#fff;border-bottom:1px solid #e4ebef;flex-shrink:0}.detail-heading h2{margin:4px 0 0}
.detail-eyebrow{font-size:11px;letter-spacing:2px;color:#217c70}.detail-heading-actions{display:flex;align-items:center;gap:14px}
.status-badge{background:#e7f5ee;color:#217c70;border-radius:20px;padding:6px 12px;font-size:12px;font-weight:600}.status-badge.failed{background:#fff0f0;color:#b83232}
.detail-body{padding:22px 26px;overflow:auto;min-height:0}.request-overview{display:flex;align-items:center;gap:12px;flex-wrap:wrap;font-size:12px;color:#64748b;margin-bottom:18px}.request-overview code{color:#334155;overflow-wrap:anywhere}
.metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.metric-grid>div{display:grid;gap:9px;padding:16px;background:#fff;border:1px solid #e4ebef;border-radius:12px;min-width:0}.metric-grid span,.metric-grid small{font-size:12px;color:#718096}.metric-grid strong{font-size:21px;color:#253a47;overflow-wrap:anywhere}
.timing-strip{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0 22px;font-size:12px;color:#64748b}.timing-strip b{font-weight:500;color:#34495a;margin-left:8px}.detail-error{padding:12px;background:#fff0f0;border-radius:8px;color:#b83232}
.raw-section,.image-section{padding:20px;background:#fff;border:1px solid #e4ebef;border-radius:12px}.section-heading h3{margin:0}.section-heading p{margin:6px 0 16px}.raw-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px}.raw-tabs button{background:#f7f9fb;border-color:transparent;color:#64748b}.raw-tabs button.active{background:#e7f4f0;color:#176d62;border-color:#b8ded2;font-weight:600}
.raw-viewer{border:1px solid #dce6ec;border-radius:10px;overflow:hidden}.raw-toolbar{padding:10px 14px;background:#f4f7f9;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;font-size:12px;color:#64748b}.raw-toolbar>div{display:flex;gap:8px;align-items:center}.raw-toolbar button{min-height:28px;font-size:12px;padding:3px 10px}.raw-toolbar a{color:#217c70;text-decoration:none;margin-left:4px}
.raw-code{margin:0;border-radius:0;padding:18px;max-height:44vh;min-height:160px;line-height:1.7;white-space:pre-wrap;overflow-wrap:anywhere;tab-size:2}.raw-footer{padding:8px 14px;font-size:11px;color:#718096;background:#f7f9fb}.raw-state,.detail-empty{padding:28px;text-align:center;color:#64748b}.preview-limit{margin:0;padding:10px 14px;background:#fff7e6;color:#98661d;font-size:12px}
.headers-section,.archive-downloads{margin-top:18px;border-top:1px solid #edf1f4;padding-top:14px}summary{cursor:pointer;color:#385466;font-size:13px;font-weight:600}.headers-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.headers-grid h4{font-size:12px;color:#64748b}.headers-grid pre{max-height:240px;white-space:pre-wrap;overflow-wrap:anywhere}.archive-downloads .download-list{margin-top:12px}.image-section{margin-top:18px}
@media(max-width:760px){.call-detail{width:calc(100vw - 24px)}.detail-heading,.detail-body{padding:16px}.metric-grid,.headers-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.raw-section{padding:14px}.raw-toolbar>div{flex-wrap:wrap}}
.call-detail h3{margin:18px 0 8px;font-size:14px}
.download-list{display:flex;flex-wrap:wrap;gap:12px}
.download-list a{color:#217c70;font-size:13px}
.image-list{display:flex;flex-wrap:wrap;gap:12px}
.image-list figure{margin:0;width:180px}
.image-list img{width:180px;height:140px;object-fit:contain;background:#f4f7f8;border-radius:8px}
.image-list figcaption{overflow-wrap:anywhere;font-size:12px}
pre{padding:12px;overflow:auto;background:#102630;color:#e2f5ed;border-radius:8px;font-size:12px}
.warning{color:#c62f2f}
</style>
