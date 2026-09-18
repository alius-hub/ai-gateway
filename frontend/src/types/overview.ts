export interface OverviewSummary {
  total_requests: number;
  total_tokens: number;
  total_cost: string;
  organization_count: number;
  project_count: number;
  key_count: number;
  provider_count: number;
  model_count: number;
  node_count: number;
  active_node_count: number;
  healthy_provider_count: number;
  data_source: "database" | "bootstrap";
  database_status: "connected" | "unavailable";
  status_message: string;
  generated_at: string;
}
