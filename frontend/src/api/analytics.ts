import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type {
  AnalyticsQuery, CostAnalytics, PerformanceAnalytics, UsageAnalytics,
} from "@/types/analytics";

function params(query: AnalyticsQuery) {
  return {
    start_date: query.start_date,
    end_date: query.end_date,
    dimension: query.dimension,
    scope: query.scope || undefined,
    value: query.scope ? query.value : undefined,
  };
}

export async function fetchUsage(query: AnalyticsQuery): Promise<UsageAnalytics> {
  const result = await http.get<ApiEnvelope<UsageAnalytics>, ApiEnvelope<UsageAnalytics>>(
    "/analytics/usage", { params: params(query) },
  );
  return result.data;
}

export async function fetchCost(query: AnalyticsQuery, currency: string): Promise<CostAnalytics> {
  const result = await http.get<ApiEnvelope<CostAnalytics>, ApiEnvelope<CostAnalytics>>(
    "/analytics/cost", { params: { ...params(query), currency } },
  );
  return result.data;
}

export async function fetchCurrencies(): Promise<string[]> {
  const result = await http.get<ApiEnvelope<string[]>, ApiEnvelope<string[]>>(
    "/analytics/currencies",
  );
  return result.data;
}

export async function fetchPerformance(query: AnalyticsQuery): Promise<PerformanceAnalytics> {
  const result = await http.get<ApiEnvelope<PerformanceAnalytics>, ApiEnvelope<PerformanceAnalytics>>(
    "/analytics/performance", { params: params(query) },
  );
  return result.data;
}
