import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";

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
  role?: string;
  description?: string | null;
  status: number;
  member_status?: number;
  children?: IdentityRecord[];
}

export type IdentityPayload = Record<string, string | number | null>;

async function unwrap<T>(request: Promise<ApiEnvelope<T>>): Promise<T> {
  return (await request).data;
}

export function listIdentity(kind: IdentityKind, params: Record<string, string | number> = {}) {
  return unwrap(http.get<ApiEnvelope<PageResult<IdentityRecord>>, ApiEnvelope<PageResult<IdentityRecord>>>(
    `/${kind}`, { params },
  ));
}

export function organizationTree() {
  return unwrap(http.get<ApiEnvelope<IdentityRecord[]>, ApiEnvelope<IdentityRecord[]>>("/organizations/tree"));
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
