import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import { encodeFilter, type FilterGroup } from "@/types/filter";
import type { ProviderItem } from "@/types/resource";

export interface ProviderPayload {
  name: string;
  code: string;
  provider_type: string;
  base_url: string;
  api_key?: string;
  additional_protocols?: { code: string; protocol_type: string; base_url: string }[];
  secrets?: { name: string; api_key: string }[];
  status?: number;
}

export interface ProviderProtocol {
  id: number;
  provider_id: number;
  code: string;
  protocol_type: string;
  base_url: string;
  status: number;
}

export interface ProviderSecret {
  id: number;
  provider_id: number;
  name: string;
  status: number;
}

async function unwrap<T>(request: Promise<ApiEnvelope<T>>): Promise<T> {
  return (await request).data;
}

export function listProviders(params: { page: number; page_size: number; keyword: string; filters?: FilterGroup }) {
  return unwrap(http.get<ApiEnvelope<PageResult<ProviderItem>>, ApiEnvelope<PageResult<ProviderItem>>>(
    "/providers", { params: { ...params, filters: encodeFilter(params.filters) } },
  ));
}

export function createProvider(payload: ProviderPayload) {
  return unwrap(http.post<ApiEnvelope<ProviderItem>, ApiEnvelope<ProviderItem>>("/providers", payload));
}

export function updateProvider(id: number, payload: Pick<ProviderPayload, "name" | "code">) {
  return unwrap(http.patch<ApiEnvelope<ProviderItem>, ApiEnvelope<ProviderItem>>(`/providers/${id}`, payload));
}

export function setProviderStatus(id: number, status: number) {
  return unwrap(http.patch<ApiEnvelope<ProviderItem>, ApiEnvelope<ProviderItem>>(`/providers/${id}/status`, { status }));
}

export function listProtocols(id: number) {
  return unwrap(http.get<ApiEnvelope<ProviderProtocol[]>, ApiEnvelope<ProviderProtocol[]>>(`/providers/${id}/protocols`));
}

export function createProtocol(id: number, payload: { code: string; protocol_type: string; base_url: string }) {
  return unwrap(http.post<ApiEnvelope<ProviderProtocol>, ApiEnvelope<ProviderProtocol>>(`/providers/${id}/protocols`, payload));
}

export function updateProtocol(id: number, protocolId: number, payload: Partial<ProviderProtocol>) {
  return unwrap(http.patch<ApiEnvelope<ProviderProtocol>, ApiEnvelope<ProviderProtocol>>(
    `/providers/${id}/protocols/${protocolId}`, payload,
  ));
}

export function listSecrets(id: number) {
  return unwrap(http.get<ApiEnvelope<ProviderSecret[]>, ApiEnvelope<ProviderSecret[]>>(`/providers/${id}/secrets`));
}

export function createSecret(id: number, name: string, api_key: string) {
  return unwrap(http.post<ApiEnvelope<ProviderSecret>, ApiEnvelope<ProviderSecret>>(
    `/providers/${id}/secrets`, { name, api_key },
  ));
}

export function updateSecret(id: number, secretId: number, payload: { api_key?: string; status?: number }) {
  return unwrap(http.patch<ApiEnvelope<ProviderSecret>, ApiEnvelope<ProviderSecret>>(
    `/providers/${id}/secrets/${secretId}`, payload,
  ));
}
