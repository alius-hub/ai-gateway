<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { useRoute } from "vue-router";

import AppListFilter from "@/AppListFilter.vue";
import AppFilterTags from "@/AppFilterTags.vue";
import { getCallImage, getCallLog, listCallLogs, type CallLog, type CallLogDetail } from "@/api/logs";
import type { FilterGroup } from "@/types/filter";
import { listFilterFields } from "@/utils/listFilterFields";
import { showToast } from "@/utils/toast";

const items = ref<CallLog[]>([]);
const route = useRoute();
const page = ref(1);
const total = ref(0);
const query = ref("");
const activeQuery = ref("");
const filters = ref<FilterGroup>({ mode: "and", conditions: [] });
const loading = ref(false);
const selected = ref<CallLogDetail | null>(null);
const detailLoading = ref(false);
const previews = ref<Record<number, string>>({});
let generation = 0;
let detailGeneration = 0;

const pages = computed(() => Math.max(1, Math.ceil(total.value / 20)));

async function load() {
  const current = ++generation;
  items.value = [];
  loading.value = true;
  try {
    const result = await listCallLogs(page.value, activeQuery.value, filters.value);
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

function changePage(next: number) {
  page.value = next;
  void load();
}

async function openDetail(requestId: string) {
  const current = ++detailGeneration;
  clearPreviews();
  detailLoading.value = true;
  selected.value = null;
  try {
    const detail = await getCallLog(requestId);
    if (current !== detailGeneration) return;
    selected.value = detail;
    detailLoading.value = false;
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
        <thead><tr><th>时间</th><th>请求 ID</th><th>模型</th><th>接入模型 ID</th><th>来源 IP</th><th>状态</th><th>耗时</th><th>输入 / 输出 Token</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="item in items" :key="item.request_id">
            <td>{{ new Date(item.created_at).toLocaleString() }}</td>
            <td class="request-id">{{ item.request_id }}</td>
            <td>{{ item.model }}</td>
            <td>{{ item.provider_model_id ?? "-" }}</td>
            <td>{{ item.requester_ip }}</td>
            <td>{{ item.http_status }}<span v-if="item.error_code"> · {{ item.error_code }}</span></td>
            <td>{{ item.latency_ms ?? "-" }} ms</td>
            <td>{{ item.input_tokens ?? "-" }} / {{ item.output_tokens ?? "-" }}</td>
            <td><button type="button" @click="openDetail(item.request_id)">详情</button></td>
          </tr>
          <tr v-if="!items.length"><td colspan="9" class="empty">{{ loading ? "正在加载..." : "暂无调用日志" }}</td></tr>
        </tbody>
      </table>
      <footer class="call-pages">
        <span>共 {{ total }} 条</span>
        <button type="button" :disabled="page <= 1 || loading" @click="changePage(page - 1)">上一页</button>
        <span>{{ page }} / {{ pages }}</span>
        <button type="button" :disabled="page >= pages || loading" @click="changePage(page + 1)">下一页</button>
      </footer>
    </div>
    <div v-if="selected || detailLoading" class="app-modal-overlay" @click.self="closeDetail">
      <div class="app-modal-panel call-detail" role="dialog" aria-modal="true" aria-label="调用日志详情">
        <header><h2>调用详情</h2><button type="button" @click="closeDetail">关闭</button></header>
        <p v-if="detailLoading">正在加载...</p>
        <template v-else-if="selected">
          <p>请求 ID：{{ selected.request_id }}</p>
          <p>模型：{{ selected.model }} · 状态：{{ selected.http_status }} · Token：{{ selected.total_tokens ?? "-" }}</p>
          <p>接入模型 ID：{{ selected.provider_model_id ?? "-" }} · 上游状态：{{ selected.provider_status ?? "-" }} · 错误：{{ selected.error_code ?? "-" }}</p>
          <p v-if="selected.error_message">{{ selected.error_message }}</p>
          <p>来源 IP：{{ selected.requester_ip }} · 输入 Token：{{ selected.input_tokens ?? "-" }} · 输出 Token：{{ selected.output_tokens ?? "-" }}</p>
          <p>思考 Token：{{ selected.reasoning_tokens ?? "-" }} · 非思考 Token：{{ selected.non_reasoning_tokens ?? "-" }}</p>
          <p>TTFT：{{ selected.ttft_ms == null ? "-" : `${selected.ttft_ms} ms` }} · TPOT：{{ selected.tpot_ms == null ? "-" : `${selected.tpot_ms} ms/token` }} · 总耗时：{{ selected.latency_ms ?? "-" }} ms</p>
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
            <h3>原始文件</h3>
            <div class="download-list">
              <a v-for="(url, name) in selected.archive.downloads" :key="name"
                 :href="url" target="_blank" rel="noopener noreferrer">{{ name }}（60 秒有效）</a>
            </div>
            <h3>客户端请求头</h3>
            <pre>{{ JSON.stringify(selected.archive.manifest?.request_headers, null, 2) }}</pre>
            <h3>上游请求头</h3>
            <pre>{{ JSON.stringify(selected.archive.manifest?.upstream_request_headers, null, 2) }}</pre>
            <h3>上游响应头</h3>
            <pre>{{ JSON.stringify(selected.archive.manifest?.upstream_response_headers, null, 2) }}</pre>
            <h3>客户端响应头</h3>
            <pre>{{ JSON.stringify(selected.archive.manifest?.response_headers, null, 2) }}</pre>
            <p v-for="image in selected.archive.manifest?.external_images" :key="image.url">
              外链图片：{{ image.url }} · {{ image.saved ? "已保存" : `未保存（${image.error}）` }}
            </p>
          </template>
        </template>
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
.call-detail{box-sizing:border-box;width:90vw;height:90vh;height:90dvh;overflow:auto;padding:24px}
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
