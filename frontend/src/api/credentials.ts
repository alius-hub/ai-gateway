import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import { encodeFilter, type FilterGroup } from "@/types/filter";

export type KeyScope = "user" | "project";

export interface CredentialSettings {
  name: string;
  aggregate_model_ids: number[];
  access_model_ids: number[];
  expires_at: string | null;
  tpm_limit: number | null;
  qps_limit: number | null;
  token_budget: number | null;
  amount_budget: number | null;
  budget_period: "week" | "month" | null;
  wait_mode: "queue" | "block";
  max_wait_ms: number;
}

export interface CredentialItem extends CredentialSettings {
  id: number;
  scope_type: KeyScope;
  user_id: number | null;
  owner_name: string | null;
  project_id: number | null;
  organization_id: number | null;
  key_prefix: string;
  custom_prefix: string | null;
  revealable: boolean;
  status: number;
  created_at: string;
}

export interface CredentialSecret {
  api_key: string;
  models: { id: string; model_type: string }[];
}

export type CreatedCredential = CredentialItem & CredentialSecret;

const path = (scope: KeyScope) => `/credentials/${scope === "user" ? "user-keys" : "project-keys"}`;

async function unwrap<T>(request: Promise<ApiEnvelope<T>>): Promise<T> {
  return (await request).data;
}

export function listCredentials(scope: KeyScope, page: number, pageSize: number, filters?: FilterGroup) {
  return unwrap(http.get<ApiEnvelope<PageResult<CredentialItem>>, ApiEnvelope<PageResult<CredentialItem>>>(
    path(scope), { params: { page, page_size: pageSize, filters: encodeFilter(filters) } },
  ));
}

export function createCredential(scope: KeyScope, payload: CredentialSettings & { user_id?: number; project_id?: number; custom_prefix?: string | null }) {
  return unwrap(http.post<ApiEnvelope<CreatedCredential>, ApiEnvelope<CreatedCredential>>(path(scope), payload));
}

export function updateCredential(scope: KeyScope, id: number, payload: CredentialSettings) {
  return unwrap(http.put<ApiEnvelope<CredentialItem>, ApiEnvelope<CredentialItem>>(`${path(scope)}/${id}`, payload));
}

export function rotateCredential(scope: KeyScope, id: number, customPrefix?: string | null) {
  return unwrap(http.post<ApiEnvelope<CreatedCredential>, ApiEnvelope<CreatedCredential>>(
    `${path(scope)}/${id}/rotate`,
    customPrefix === undefined ? undefined : { custom_prefix: customPrefix },
  ));
}

export function revealCredential(scope: KeyScope, id: number) {
  return unwrap(http.get<ApiEnvelope<CredentialSecret>, ApiEnvelope<CredentialSecret>>(
    `${path(scope)}/${id}/secret`,
  ));
}

export function setCredentialStatus(scope: KeyScope, id: number, status: number) {
  return unwrap(http.patch<ApiEnvelope<CredentialItem>, ApiEnvelope<CredentialItem>>(
    `${path(scope)}/${id}/status`, { status },
  ));
}
