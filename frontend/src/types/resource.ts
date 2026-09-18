export interface OrganizationItem {
  id: number;
  name: string;
  code: string;
  status: number;
  description?: string | null;
}

export interface ProjectItem {
  id: number;
  organization_id: number;
  name: string;
  code: string;
  environment: string;
  status: number;
  description?: string | null;
}

export interface CredentialItem {
  id: number;
  organization_id: number;
  project_id?: number | null;
  name: string;
  scope_type: string;
  status: number;
  key_prefix: string;
}

export interface ProviderItem {
  id: number;
  name: string;
  code: string;
  provider_type: string;
  base_url?: string;
  status: number;
  health_status: string;
}

export interface AccessModelItem {
  id: number;
  provider_id: number;
  access_model_code: string;
  provider_model_name: string;
  model_type: string;
  status: number;
  currency?: string;
}

export interface AggregateModelItem {
  id: number;
  aggregate_model_code: string;
  public_model_name: string;
  model_type: string;
  default_routing_strategy: string;
  status: number;
  description?: string | null;
}

export interface NodeItem {
  id: number;
  node_code: string;
  node_name: string;
  provider_id: number;
  provider_model_id: number;
  model_type: string;
  status: number;
  health_status: string;
  weight: number;
  priority: number;
  region?: string | null;
}
