import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import type {
  AccessModelItem,
  AggregateModelItem,
  CredentialItem,
  NodeItem,
  OrganizationItem,
  ProjectItem,
  ProviderItem,
} from "@/types/resource";

async function getPage<T>(url: string): Promise<PageResult<T>> {
  const response = await http.get<ApiEnvelope<PageResult<T>>, ApiEnvelope<PageResult<T>>>(url);
  return response.data;
}

export function fetchOrganizations() {
  return getPage<OrganizationItem>("/organizations");
}

export function fetchProjects() {
  return getPage<ProjectItem>("/projects");
}

export function fetchCredentials() {
  return getPage<CredentialItem>("/credentials/project-keys");
}

export function fetchProviders() {
  return getPage<ProviderItem>("/providers");
}

export function fetchAccessModels() {
  return getPage<AccessModelItem>("/access-models");
}

export function fetchAggregateModels() {
  return getPage<AggregateModelItem>("/aggregate-models");
}

export function fetchNodes() {
  return getPage<NodeItem>("/nodes");
}
