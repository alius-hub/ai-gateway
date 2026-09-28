import type { AnalyticsQuery } from "@/types/analytics";
import type { FilterCondition } from "@/types/filter";

export function analyticsLogFilters(query: AnalyticsQuery, extra: FilterCondition[] = []): string {
  const tomorrow = new Date(`${query.end_date}T00:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  const conditions: FilterCondition[] = [
    { field: "created_at", operator: "gte", value: query.start_date },
    { field: "created_at", operator: "lt", value: tomorrow.toISOString().slice(0, 10) },
  ];
  if (query.scope) {
    conditions.push(query.value === "none"
      && ["organization", "project", "key", "provider", "access_model"].includes(query.scope)
      ? { field: `${query.scope}_unassigned`, operator: "eq", value: "1" }
      : { field: query.scope, operator: "eq", value: query.value });
  }
  return JSON.stringify({ mode: "and", conditions: [...conditions, ...extra] });
}
