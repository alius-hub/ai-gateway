import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import { encodeFilter, type FilterGroup } from "@/types/filter";

export interface AuditEvent {
  id: number;
  actor_user_id: number | null;
  actor_username: string;
  action: string;
  resource: string;
  method: string;
  path: string;
  ip_address: string | null;
  status_code: number;
  created_at: string;
}

export async function listAuditResources(): Promise<string[]> {
  const response = await http.get<ApiEnvelope<string[]>, ApiEnvelope<string[]>>(
    "/logs/audit-resources",
  );
  return response.data;
}

export async function listAuditEvents(page: number, pageSize: number, query: {
  actor_user_id?: number; action?: string; resource?: string;
  start_time?: string; end_time?: string;
}, filters?: FilterGroup): Promise<{ items: AuditEvent[]; total: number; page: number; page_size: number }> {
  const response = await http.get<ApiEnvelope<{ items: AuditEvent[]; total: number; page: number; page_size: number }>,
    ApiEnvelope<{ items: AuditEvent[]; total: number; page: number; page_size: number }>>(
    "/logs/audit-events", { params: { page, page_size: pageSize, ...query, filters: encodeFilter(filters) } },
  );
  return response.data;
}

export interface CallLog {
  request_id: string;
  created_at: string;
  organization_id: number | null;
  project_id: number | null;
  api_key_id: number | null;
  model: string;
  model_type: string;
  provider_id: number | null;
  provider_model_id: number | null;
  provider_status: string | null;
  error_message: string | null;
  requester_ip: string;
  endpoint: string;
  http_status: number;
  latency_ms: number | null;
  ttft_ms: number | null;
  tpot_ms: number | null;
  error_code: string | null;
  total_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  non_reasoning_tokens: number | null;
}

export interface CallLogDetail extends CallLog {
  images: { kind: "url" | "inline" | "base64"; url: string | null; index: number }[];
  archive: null | {
    status: "pending" | "stored" | "unavailable";
    manifest?: {
      request_headers: string[][];
      response_headers?: string[][];
      upstream_request_headers?: string[][];
      upstream_response_headers?: string[][];
      external_images?: { url: string; saved: boolean; error?: string }[];
      capture_complete: boolean;
    };
    downloads?: Record<string, string>;
  };
}

type CallPage = {
    items: CallLog[];
    page: number;
    page_size: number;
    total: number;
};

export async function listCallLogs(page: number, requestId: string, filters?: FilterGroup): Promise<CallPage> {
  const response = await http.get<ApiEnvelope<CallPage>, ApiEnvelope<CallPage>>(
    "/logs/requests", { params: { page, page_size: 20, request_id: requestId || undefined, filters: encodeFilter(filters) } },
  );
  return response.data;
}

export async function getCallLog(requestId: string): Promise<CallLogDetail> {
  const response = await http.get<ApiEnvelope<CallLogDetail>, ApiEnvelope<CallLogDetail>>(
    `/logs/requests/${encodeURIComponent(requestId)}`,
  );
  return response.data;
}

export async function getCallImage(requestId: string, index: number): Promise<Blob> {
  return http.get<Blob, Blob>(
    `/logs/requests/${encodeURIComponent(requestId)}/images/${index}`,
    { responseType: "blob" },
  );
}
