const ACCESS_TOKEN_KEY = "ai-gateway-access-token";
const USER_INFO_KEY = "ai-gateway-user-info";

export function getAccessToken(): string {
  return localStorage.getItem(ACCESS_TOKEN_KEY) ?? "";
}

export function setAccessToken(token: string) {
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function removeAccessToken() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
}

export function getUserCache(): string {
  return localStorage.getItem(USER_INFO_KEY) ?? "";
}

export function setUserCache(userInfo: string) {
  localStorage.setItem(USER_INFO_KEY, userInfo);
}

export function removeUserCache() {
  localStorage.removeItem(USER_INFO_KEY);
}
