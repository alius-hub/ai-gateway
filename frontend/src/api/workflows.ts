import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";
import { encodeFilter, type FilterGroup } from "@/types/filter";

export type StrategyCode = "single" | "round_robin" | "least_latency";
export interface BuiltinStrategy {
  code: StrategyCode;
  name: string;
  description: string;
  min_models: number;
}
export interface AggregatePayload {
  aggregate_model_code: string;
  public_model_name: string;
  model_type: string;
  default_routing_strategy: StrategyCode;
  routing_model_ids: number[];
  fallback_model_id: number | null;
  retry_on_failure: boolean;
  description: string | null;
  status: number;
}
export interface AggregateItem extends Omit<AggregatePayload, "default_routing_strategy"> {
  id: number;
  default_routing_strategy: string;
  workflow_id: number | null;
  workflow_bindings: Record<string, number[]>;
}
export interface AggregateNode {
  model_id: number;
  access_model_code: string;
  role: "candidate" | "fallback" | "candidate_and_fallback";
  status: "available" | "cooldown" | "disabled" | "missing";
  cooldown_seconds: number;
  ttft_samples: number;
  avg_ttft_ms: number | null;
  tps_samples: number;
  avg_tps: number | null;
}
export interface AggregateNodes {
  nodes: AggregateNode[];
  window_hours: number;
}
export interface AggregateProbeResult {
  model_id: number;
  result: "ok" | "failed" | "unsupported";
  message: string;
  latency_ms: number;
  http_status: number | null;
}

const unwrap = async <T>(request: Promise<ApiEnvelope<T>>): Promise<T> => (await request).data;

export const listBuiltinStrategies = () => unwrap(http.get<ApiEnvelope<{ items: BuiltinStrategy[] }>, ApiEnvelope<{ items: BuiltinStrategy[] }>>("/routing/strategies"));
export const listAggregates = (params: { page?: number; page_size?: number; keyword?: string; filters?: FilterGroup } = {}) => unwrap(http.get<ApiEnvelope<PageResult<AggregateItem>>, ApiEnvelope<PageResult<AggregateItem>>>(
  "/aggregate-models", { params: { ...params, filters: encodeFilter(params.filters) } },
));
export const createAggregate = (payload: AggregatePayload) => unwrap(http.post<ApiEnvelope<AggregateItem>, ApiEnvelope<AggregateItem>>("/aggregate-models", payload));
export const updateAggregate = (id: number, payload: AggregatePayload) => unwrap(http.put<ApiEnvelope<AggregateItem>, ApiEnvelope<AggregateItem>>(`/aggregate-models/${id}`, payload));
export const getAggregateNodes = (id: number) => unwrap(http.get<ApiEnvelope<AggregateNodes>, ApiEnvelope<AggregateNodes>>(`/aggregate-models/${id}/nodes`));
export const probeAggregateNodes = (id: number, model_ids: number[], mode: "network" | "actual") => unwrap(
  http.post<ApiEnvelope<{ results: AggregateProbeResult[] }>, ApiEnvelope<{ results: AggregateProbeResult[] }>>(
    `/aggregate-models/${id}/nodes/probe`, { model_ids, mode },
  ),
);
