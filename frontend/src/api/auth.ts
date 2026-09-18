import { http } from "@/api/http";
import type { ApiEnvelope } from "@/types/api";
import type { LoginPayload, LoginResponse, UserInfo } from "@/types/auth";

export async function login(payload: LoginPayload): Promise<LoginResponse> {
  const response = await http.post<ApiEnvelope<LoginResponse>, ApiEnvelope<LoginResponse>>(
    "/auth/login",
    payload,
  );
  return response.data;
}

export async function fetchCurrentUser(): Promise<UserInfo> {
  const response = await http.get<ApiEnvelope<UserInfo>, ApiEnvelope<UserInfo>>("/auth/me");
  return response.data;
}
