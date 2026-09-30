import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import { encodeFilter, type FilterGroup } from "@/types/filter";

export type Metric = "error_rate" | "key_token_usage" | "project_amount_usage";
export type Recipient = { receive_id_type: "open_id" | "chat_id"; receive_id: string };
export type TestPushResult = Recipient & { sent: boolean; error: string | null };
export type AlertRulePayload = {
  name: string; metric: Metric; scope_id: number | null; threshold: number;
  window_minutes: number; min_samples: number; level: "warning" | "critical"; enabled: boolean;
  recipients: Recipient[];
};
export type AlertRule = AlertRulePayload & { id: number; created_at: string };
export type AlertEvent = {
  id: number; rule_id: number; rule_name: string; metric: Metric; scope_id: number | null;
  level: string; status: "open" | "acknowledged" | "resolved";
  current_value: number; threshold: number; triggered_at: string;
  acknowledged_at: string | null; acknowledged_by: number | null; resolved_at: string | null;
};
export type Delivery = Recipient & { id: number; kind: string; status: string; attempts: number; last_error: string | null; sent_at: string | null };
export type FeishuConfig = { app_id: string; chat_id: string; enabled: boolean; has_secret: boolean };

async function get<T>(path: string, params?: object): Promise<T> {
  const result = await http.get<ApiEnvelope<T>, ApiEnvelope<T>>(path, { params });
  return result.data;
}
async function post<T>(path: string, payload?: object): Promise<T> {
  const result = await http.post<ApiEnvelope<T>, ApiEnvelope<T>>(path, payload);
  return result.data;
}

export const listAlertRules = (page: number, pageSize: number, filters?: FilterGroup) =>
  get<{ items: AlertRule[]; total: number }>("/alerts/rules", { page, page_size: pageSize, filters: encodeFilter(filters) });
export const listAlertEvents = (page: number, status?: string, filters?: FilterGroup, pageSize = 20) =>
  get<{ items: AlertEvent[]; total: number }>("/alerts/events", { page, page_size: pageSize, status: status || undefined, filters: encodeFilter(filters) });
export const getFeishuConfig = () => get<FeishuConfig>("/alerts/settings/feishu");
export const saveFeishuConfig = (payload: { app_id: string; app_secret?: string; chat_id: string; enabled: boolean }) =>
  http.put("/alerts/settings/feishu", payload);
export const testFeishuConfig = () => post("/alerts/settings/feishu/test");
export const saveAlertRule = (payload: AlertRulePayload, id?: number) =>
  id ? http.patch(`/alerts/rules/${id}`, payload) : http.post("/alerts/rules", payload);
export const deleteAlertRule = (id: number) => http.delete(`/alerts/rules/${id}`);
export const testAlertRule = async (id: number) => {
  const result = await http.post<ApiEnvelope<{ results: TestPushResult[] }>, ApiEnvelope<{ results: TestPushResult[] }>>(
    `/alerts/rules/${id}/test`, undefined, { timeout: 180000 },
  );
  return result.data;
};
export const actionAlertEvent = (id: number, action: "ack" | "resolve") =>
  post(`/alerts/events/${id}/${action}`);
export const listAlertDeliveries = (id: number) => get<Delivery[]>(`/alerts/events/${id}/deliveries`);
