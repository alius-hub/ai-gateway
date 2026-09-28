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

export interface OverviewActivity {
  days: number;
  total_requests: number;
  successful_requests: number;
  total_tokens: number;
  daily: { date: string; requests: number; successes: number; tokens: number }[];
  top_models: { name: string; requests: number }[];
  recent_failures: { request_id: string; model: string; http_status: number; created_at: string }[];
  generated_at: string;
}
