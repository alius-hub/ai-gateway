export type FilterOperator = "contains" | "eq" | "ne" | "gt" | "gte" | "lt" | "lte";
export type FilterMode = "and" | "or";

export interface FilterCondition {
  field: string;
  operator: FilterOperator;
  value: string;
}

export interface FilterGroup {
  mode: FilterMode;
  conditions: FilterCondition[];
}

export interface FilterField {
  key: string;
  label: string;
  type: "text" | "number" | "decimal" | "date" | "select";
  options?: { label: string; value: string }[];
}

export function encodeFilter(group?: FilterGroup): string | undefined {
  return group?.conditions.length ? JSON.stringify(group) : undefined;
}
