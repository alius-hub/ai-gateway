export type Dimension =
  | "organization" | "project" | "key" | "public_model" | "access_model"
  | "provider" | "endpoint" | "model_type";

export interface AnalyticsQuery {
  start_date: string;
  end_date: string;
  dimension: Dimension;
  scope: Dimension | "";
  value: string;
}

export interface RankingIdentity {
  value: string;
  label: string;
}

export interface UsageMetrics {
  requests: number;
  successes: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface UsageAnalytics {
  start_date: string;
  end_date: string;
  dimension: Dimension;
  summary: UsageMetrics;
  daily: (UsageMetrics & { date: string })[];
  ranking: (UsageMetrics & RankingIdentity)[];
}

export interface CostMetrics {
  priced_requests: number;
  estimated_cost: string;
}

export interface CostAnalytics {
  start_date: string;
  end_date: string;
  currency: string;
  dimension: Dimension;
  summary: CostMetrics & {
    requests: number;
    unpriced_requests: number;
    average_cost: string | null;
  };
  daily: (CostMetrics & { date: string })[];
  ranking: (CostMetrics & RankingIdentity)[];
}

export interface PerformanceMetrics {
  requests: number;
  successes: number;
  latency_samples: number;
  avg_latency_ms: number | null;
  ttft_samples: number;
  avg_ttft_ms: number | null;
  tpot_samples: number;
  avg_tpot_ms: number | null;
  speed_samples: number;
  avg_tokens_per_second: number | null;
}

export interface PerformanceRanking extends PerformanceMetrics, RankingIdentity {
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
}

export interface PerformanceAnalytics {
  start_date: string;
  end_date: string;
  dimension: Dimension;
  summary: PerformanceMetrics & {
    p95_latency_ms: number | null;
    p99_latency_ms: number | null;
  };
  daily: (PerformanceMetrics & {
    date: string;
    p95_latency_ms: number | null;
    p99_latency_ms: number | null;
  })[];
  ranking: PerformanceRanking[];
  errors: { code: string; http_status: number; requests: number }[];
}

export const dimensionNames: Record<Dimension, string> = {
  organization: "组织",
  project: "项目",
  key: "API Key",
  public_model: "对外模型",
  access_model: "接入模型",
  provider: "供应商",
  endpoint: "接口",
  model_type: "模型类型",
};

export const allDimensions = Object.keys(dimensionNames) as Dimension[];

export function initialQuery(dimension: Dimension): AnalyticsQuery {
  const today = new Date();
  const first = new Date(today);
  first.setUTCDate(first.getUTCDate() - 6);
  return {
    start_date: first.toISOString().slice(0, 10),
    end_date: today.toISOString().slice(0, 10),
    dimension, scope: "", value: "",
  };
}
