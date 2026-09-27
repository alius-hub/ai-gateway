<script setup lang="ts">
import { onMounted, ref } from "vue";

import { getLogArchivePolicy, updateLogArchivePolicy, type ImageMode } from "@/api/settings";
import { showToast } from "@/utils/toast";

const imageMode = ref<ImageMode>("content_only");
const savedMode = ref<ImageMode>("content_only");
const loading = ref(true);
const saving = ref(false);

onMounted(async () => {
  try {
    const policy = await getLogArchivePolicy();
    imageMode.value = policy.image_mode;
    savedMode.value = policy.image_mode;
  } catch {
    showToast("error", "加载日志归档设置失败");
  } finally {
    loading.value = false;
  }
});

async function save() {
  saving.value = true;
  try {
    const policy = await updateLogArchivePolicy(imageMode.value);
    imageMode.value = policy.image_mode;
    savedMode.value = policy.image_mode;
    showToast("success", "日志归档设置已保存");
  } catch {
    showToast("error", "保存日志归档设置失败");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <section class="page-stack">
    <div class="page-card policy-card">
      <h2>日志归档设置</h2>
      <p>启用调用归档后，原始请求头、请求体、响应及流式数据会归档到 RustFS。此项只控制外链图片的抓取方式。</p>
      <p v-if="loading">正在加载设置...</p>
      <fieldset v-else>
        <legend>外链图片归档</legend>
        <label>
          <input v-model="imageMode" type="radio" value="content_only" />
          <span><strong>只保留原始内容</strong><small>保存原始请求/响应和图片 URL；内嵌 base64 图片已包含在原始内容中，不再抓取外部 URL。</small></span>
        </label>
        <label>
          <input v-model="imageMode" type="radio" value="mirror_images" />
          <span><strong>转存外链图片到 RustFS</strong><small>后台抓取请求中的图片及生图响应 URL，保存图片本体；失败会写入日志详情。</small></span>
        </label>
      </fieldset>
      <p class="policy-notice">开启转存后，网关会主动访问调用方提供的图片 URL。请仅在可信调用方环境下使用；失效链接无法补回图片本体。</p>
      <button type="button" :disabled="loading || saving || imageMode === savedMode" @click="save">
        {{ saving ? "保存中..." : "保存设置" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.policy-card{max-width:760px}
h2{margin:0 0 8px;font-size:20px}
p{color:#64748b;font-size:13px;line-height:1.6}
fieldset{display:grid;gap:12px;margin:24px 0;border:1px solid #e1eaed;border-radius:12px;padding:18px}
legend{padding:0 6px;font-size:14px;font-weight:600}
label{display:flex;align-items:flex-start;gap:10px;padding:14px;border:1px solid #dce8e4;border-radius:10px;cursor:pointer}
label:has(input:checked){border-color:#50a992;background:#f2faf7}
label input{margin-top:4px}
label span{display:grid;gap:6px}
label strong{font-size:14px;color:#233a48}
label small{font-size:12px;color:#64748b;line-height:1.5}
.policy-notice{margin:0 0 20px;color:#a45d19}
button{min-height:38px;padding:7px 16px;border:1px solid #237c70;border-radius:9px;background:#237c70;color:#fff;cursor:pointer}
button:disabled{opacity:.5;cursor:not-allowed}
</style>
