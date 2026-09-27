import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";

export type ImageMode = "content_only" | "mirror_images";
export interface LogArchivePolicy {
  image_mode: ImageMode;
}

export async function getLogArchivePolicy(): Promise<LogArchivePolicy> {
  const response = await http.get<ApiEnvelope<LogArchivePolicy>, ApiEnvelope<LogArchivePolicy>>(
    "/settings/log-archive",
  );
  return response.data;
}

export async function updateLogArchivePolicy(imageMode: ImageMode): Promise<LogArchivePolicy> {
  const response = await http.put<ApiEnvelope<LogArchivePolicy>, ApiEnvelope<LogArchivePolicy>>(
    "/settings/log-archive", { image_mode: imageMode },
  );
  return response.data;
}
