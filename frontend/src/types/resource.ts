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
  organization_id?: number | null;
  name: string;
  code: string;
  provider_type: string;
  base_url?: string;
  status: number;
  health_status: string;
  secret_count?: number;
  protocol_count?: number;
}

export interface PriceTier {
  up_to_tokens: number | null;
  price: number;
}

export interface AccessModelItem {
  id: number;
  provider_id: number;
  protocol_id: number | null;
  secret_id: number | null;
  access_model_code: string;
  provider_model_name: string;
  model_type: string;
  base_url: string | null;
  effective_base_url: string | null;
  region: string | null;
  max_concurrency: number | null;
  context_window: number | null;
  timeout_ms: number | null;
  price_unit_k: number;
  input_price: number | null;
  output_price: number | null;
  tiered_pricing: boolean;
  input_price_tiers: PriceTier[];
  output_price_tiers: PriceTier[];
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
