import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { OverviewSummary } from "@/types/overview";

export async function fetchOverviewSummary(): Promise<OverviewSummary> {
  const response = await http.get<ApiEnvelope<OverviewSummary>, ApiEnvelope<OverviewSummary>>(
    "/overview/summary",
  );
  return response.data;
}
