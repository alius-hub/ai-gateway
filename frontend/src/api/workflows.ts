import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { PageResult } from "@/types/list";

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
  description: string | null;
  status: number;
}
export interface AggregateItem extends Omit<AggregatePayload, "default_routing_strategy"> {
  id: number;
  default_routing_strategy: string;
  workflow_id: number | null;
  workflow_bindings: Record<string, number[]>;
}

const unwrap = async <T>(request: Promise<ApiEnvelope<T>>): Promise<T> => (await request).data;

export const listBuiltinStrategies = () => unwrap(http.get<ApiEnvelope<{ items: BuiltinStrategy[] }>, ApiEnvelope<{ items: BuiltinStrategy[] }>>("/routing/strategies"));
export const listAggregates = () => unwrap(http.get<ApiEnvelope<PageResult<AggregateItem>>, ApiEnvelope<PageResult<AggregateItem>>>("/aggregate-models"));
export const createAggregate = (payload: AggregatePayload) => unwrap(http.post<ApiEnvelope<AggregateItem>, ApiEnvelope<AggregateItem>>("/aggregate-models", payload));
export const updateAggregate = (id: number, payload: AggregatePayload) => unwrap(http.put<ApiEnvelope<AggregateItem>, ApiEnvelope<AggregateItem>>(`/aggregate-models/${id}`, payload));
