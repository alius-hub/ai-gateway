import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import { encodeFilter, type FilterGroup } from "@/types/filter";

export type IdentityKind = "users" | "user-groups" | "organizations" | "projects";

export interface IdentityRecord {
  id: number;
  username?: string;
  email?: string;
  nickname?: string | null;
  is_platform_admin?: number;
  name?: string;
  code?: string;
  group_name?: string;
  group_code?: string;
  organization_id?: number | null;
  parent_id?: number | null;
  owner_user_id?: number;
  environment?: string;
  amount_budget?: number | null;
  role?: string;
  description?: string | null;
  status: number;
  member_status?: number;
  children?: IdentityRecord[];
}

export type IdentityPayload = Record<string, string | number | null>;

export interface ProjectKeySummary {
  id: number;
  name: string;
  key_prefix: string;
  user_id: number | null;
  owner_name: string | null;
  created_by: number;
  creator_name: string | null;
  status: number;
  expires_at: string | null;
  tpm_limit: number | null;
  qps_limit: number | null;
  token_budget: number | null;
  amount_budget: number | null;
  budget_period: "week" | "month" | null;
  total_tokens: number;
  total_cost: number;
  period_tokens: number;
  period_cost: number;
}

export interface ProjectKeysPage extends PageResult<ProjectKeySummary> {
  project_amount_budget: number | null;
  project_total_cost: number;
}

async function unwrap<T>(request: Promise<ApiEnvelope<T>>): Promise<T> {
  return (await request).data;
}

export function listProjectKeys(projectId: number, page: number, pageSize: number) {
  return unwrap(http.get<ApiEnvelope<ProjectKeysPage>, ApiEnvelope<ProjectKeysPage>>(
    `/projects/${projectId}/keys`, { params: { page, page_size: pageSize } },
  ));
}

export function listIdentity(kind: IdentityKind, params: {
  page?: number; page_size?: number; keyword?: string; status?: number;
  organization_id?: number; scope?: string; filters?: FilterGroup;
} = {}) {
  const { filters, ...query } = params;
  return unwrap(http.get<ApiEnvelope<PageResult<IdentityRecord>>, ApiEnvelope<PageResult<IdentityRecord>>>(
    `/${kind}`, { params: { ...query, filters: encodeFilter(filters) } },
  ));
}

export function organizationTree(filters?: FilterGroup) {
  return unwrap(http.get<ApiEnvelope<IdentityRecord[]>, ApiEnvelope<IdentityRecord[]>>(
    "/organizations/tree", { params: { filters: encodeFilter(filters) } },
  ));
}

export function createIdentity(kind: IdentityKind, payload: IdentityPayload) {
  return unwrap(http.post<ApiEnvelope<IdentityRecord>, ApiEnvelope<IdentityRecord>>(`/${kind}`, payload));
}

export function updateIdentity(kind: IdentityKind, id: number, payload: IdentityPayload) {
  return unwrap(http.patch<ApiEnvelope<IdentityRecord>, ApiEnvelope<IdentityRecord>>(`/${kind}/${id}`, payload));
}

export function resetUserPassword(id: number, password: string) {
  return unwrap(http.post<ApiEnvelope<null>, ApiEnvelope<null>>(`/users/${id}/reset-password`, { password }));
}

export function listMembers(kind: IdentityKind, id: number) {
  return unwrap(http.get<ApiEnvelope<IdentityRecord[]>, ApiEnvelope<IdentityRecord[]>>(`/${kind}/${id}/members`));
}

export function addMember(kind: IdentityKind, id: number, userId: number, role?: string) {
  return unwrap(http.post<ApiEnvelope<IdentityRecord>, ApiEnvelope<IdentityRecord>>(
    `/${kind}/${id}/members`, { user_id: userId, ...(role ? { role } : {}) },
  ));
}

export function updateMember(kind: IdentityKind, id: number, userId: number, role: string) {
  return unwrap(http.patch<ApiEnvelope<IdentityRecord>, ApiEnvelope<IdentityRecord>>(
    `/${kind}/${id}/members/${userId}`, { role },
  ));
}

export function removeMember(kind: IdentityKind, id: number, userId: number) {
  return unwrap(http.delete<ApiEnvelope<null>, ApiEnvelope<null>>(`/${kind}/${id}/members/${userId}`));
}
