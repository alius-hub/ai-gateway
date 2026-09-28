import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { OverviewActivity, OverviewSummary } from "@/types/overview";

export async function fetchOverviewSummary(): Promise<OverviewSummary> {
  const response = await http.get<ApiEnvelope<OverviewSummary>, ApiEnvelope<OverviewSummary>>(
    "/overview/summary",
  );
  return response.data;
}

export async function fetchOverviewActivity(days: 7 | 30): Promise<OverviewActivity> {
  const response = await http.get<ApiEnvelope<OverviewActivity>, ApiEnvelope<OverviewActivity>>(
    "/overview/activity", { params: { days } },
  );
  return response.data;
}
