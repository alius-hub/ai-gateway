import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import { encodeFilter, type FilterGroup } from "@/types/filter";
import { getAccessToken, removeAccessToken, removeUserCache } from "@/utils/auth";

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  source: "access" | "aggregate" | "custom";
  model_id: number | null;
  custom_protocol?: "openai" | "openai_compatible" | "claude" | "anthropic" | "gemini";
  custom_base_url?: string;
  custom_model_name?: string;
  custom_api_key?: string | null;
  messages: ChatMessage[];
  system_prompt: string;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
  stop: string[];
}

export interface ChatResult {
  content: string;
  access_model_code: string;
  protocol: string;
  latency_ms: number;
  usage: { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null };
}

export interface RawRequest extends Pick<ChatRequest, "source" | "model_id" | "custom_protocol" | "custom_base_url" | "custom_model_name" | "custom_api_key"> {
  body: Record<string, unknown>;
  headers: Record<string, string>;
  stream: boolean;
}

export interface DebugMetadata {
  model: string;
  protocol: string;
  latencyMs: string;
}

export interface DebugHistoryItem {
  id: number;
  created_at: string | null;
  mode: "conversation" | "raw";
  source: "access" | "aggregate" | "custom";
  model_code: string;
  protocol: string;
  stream: boolean;
  http_status: number | null;
  latency_ms: number | null;
  truncated: boolean;
}

export interface DebugHistoryDetail extends DebugHistoryItem {
  request_url: string;
  request_headers: Record<string, string>;
  request_body: Record<string, unknown>;
  response_body: string | null;
  parsed_content: string | null;
}

export async function listDebugHistory(page: number, pageSize = 20, filters?: FilterGroup): Promise<PageResult<DebugHistoryItem>> {
  const response = await http.get<ApiEnvelope<PageResult<DebugHistoryItem>>,
    ApiEnvelope<PageResult<DebugHistoryItem>>>("/playground/history", {
    params: { page, page_size: pageSize, filters: encodeFilter(filters) },
  });
  return response.data;
}

export async function getDebugHistory(id: number): Promise<DebugHistoryDetail> {
  const response = await http.get<ApiEnvelope<DebugHistoryDetail>,
    ApiEnvelope<DebugHistoryDetail>>(`/playground/history/${id}`);
  return response.data;
}

export async function deleteDebugHistory(id: number): Promise<void> {
  await http.delete(`/playground/history/${id}`);
}

export async function debugChat(payload: ChatRequest): Promise<ChatResult> {
  const response = await http.post<ApiEnvelope<ChatResult>, ApiEnvelope<ChatResult>>(
    "/playground/chat", payload, { timeout: 180000 },
  );
  return response.data;
}

export async function executeDebug(
  path: "chat/stream" | "raw", payload: ChatRequest | RawRequest,
  onChunk: (chunk: string, metadata: DebugMetadata) => void, signal: AbortSignal,
): Promise<DebugMetadata> {
  const response = await fetch(`${import.meta.env.VITE_ADMIN_API_BASE_URL ?? "/api/admin/v1"}/playground/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${getAccessToken()}` },
    body: JSON.stringify(payload),
    signal,
  });
  if (response.status === 401) {
    removeAccessToken();
    removeUserCache();
    window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
    throw new Error("登录已过期");
  }
  const metadata = {
    model: decodeURIComponent(response.headers.get("x-playground-model") ?? ""),
    protocol: response.headers.get("x-playground-protocol") ?? "",
    latencyMs: response.headers.get("x-playground-latency-ms") ?? "",
  };
  if (!response.ok) {
    const text = await response.text();
    if (path === "raw") onChunk(text, metadata);
    let detail = text;
    try {
      const error = JSON.parse(text) as { detail?: string };
      if (typeof error.detail === "string") detail = error.detail;
    } catch { /* Raw upstream errors may not be JSON. */ }
    throw new Error(`HTTP ${response.status}: ${detail.slice(0, 2000)}`);
  }
  if (!response.body) throw new Error("浏览器未收到响应流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      onChunk(decoder.decode(value, { stream: true }), metadata);
    }
    const remaining = decoder.decode();
    if (remaining) onChunk(remaining, metadata);
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
  return metadata;
}
