import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import type { AccessModelItem } from "@/types/resource";

export interface ModelPayload {
  provider_id: number;
  protocol_id: number;
  secret_id: number | null;
  access_model_code: string;
  provider_model_name: string;
  model_type: string;
  base_url: string | null;
  region: string | null;
  max_concurrency: number | null;
  context_window: number | null;
  timeout_ms: number | null;
}

async function unwrap<T>(request: Promise<ApiEnvelope<T>>): Promise<T> {
  return (await request).data;
}

export function listAccessModels(params: { page: number; page_size: number; provider_id?: number }) {
  return unwrap(http.get<ApiEnvelope<PageResult<AccessModelItem>>, ApiEnvelope<PageResult<AccessModelItem>>>(
    "/access-models", { params },
  ));
}

export function createAccessModel(payload: ModelPayload) {
  return unwrap(http.post<ApiEnvelope<AccessModelItem>, ApiEnvelope<AccessModelItem>>("/access-models", payload));
}

export function updateAccessModel(id: number, payload: Partial<Omit<ModelPayload, "provider_id" | "access_model_code">> & { status?: number }) {
  return unwrap(http.patch<ApiEnvelope<AccessModelItem>, ApiEnvelope<AccessModelItem>>(`/access-models/${id}`, payload));
}
