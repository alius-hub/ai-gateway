import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";

export interface CallLog {
  request_id: string;
  created_at: string;
  organization_id: number | null;
  project_id: number | null;
  api_key_id: number | null;
  model: string;
  model_type: string;
  provider_id: number | null;
  endpoint: string;
  http_status: number;
  latency_ms: number | null;
  error_code: string | null;
  total_tokens: number | null;
}

export interface CallLogDetail extends CallLog {
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

export async function listCallLogs(page: number, requestId: string): Promise<CallPage> {
  const response = await http.get<ApiEnvelope<CallPage>, ApiEnvelope<CallPage>>(
    "/logs/requests", { params: { page, page_size: 20, request_id: requestId || undefined } },
  );
  return response.data;
}

export async function getCallLog(requestId: string): Promise<CallLogDetail> {
  const response = await http.get<ApiEnvelope<CallLogDetail>, ApiEnvelope<CallLogDetail>>(
    `/logs/requests/${encodeURIComponent(requestId)}`,
  );
  return response.data;
}
