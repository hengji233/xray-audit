import client from "@/api/client";
import type {
  AccessEventRow,
  ActiveUser,
  AuthMe,
  DomainHit,
  ErrorEventRow,
  ErrorSummary,
  GeoIPItem,
  HealthResponse,
  QueryResponse,
  RuntimeConfigCurrentItem,
  RuntimeConfigHistoryItem,
  RuntimeConfigSchemaItem,
  SummaryStats,
  UserSummary,
} from "@/types";

export async function fetchSummary(window: string): Promise<SummaryStats> {
  const { data } = await client.get<SummaryStats>("/stats/summary", { params: { window } });
  return data;
}

export async function fetchErrorSummary(window: string): Promise<ErrorSummary> {
  const { data } = await client.get<ErrorSummary>("/errors/summary", { params: { window } });
  return data;
}

export async function fetchTopDomains(window: string, limit = 20): Promise<DomainHit[]> {
  const { data } = await client.get<{ items: DomainHit[] }>("/domains/top", { params: { window, limit } });
  return data.items;
}

export async function fetchActiveUsers(seconds = 30, limit = 20): Promise<ActiveUser[]> {
  const { data } = await client.get<{ items: ActiveUser[] }>("/users/active", { params: { seconds, limit } });
  return data.items;
}

export interface EventsQueryParams {
  from: string;
  to: string;
  page: number;
  page_size: number;
  email?: string;
  dest_host?: string;
  status?: string;
  detour?: string;
  is_domain?: boolean;
}

export async function queryEvents(params: EventsQueryParams): Promise<QueryResponse<AccessEventRow>> {
  const { data } = await client.get<QueryResponse<AccessEventRow>>("/events/query", { params });
  return data;
}

export interface ErrorsQueryParams {
  from: string;
  to: string;
  page: number;
  page_size: number;
  level?: string;
  category?: string;
  include_noise?: boolean;
  keyword?: string;
}

export async function queryErrors(params: ErrorsQueryParams): Promise<QueryResponse<ErrorEventRow>> {
  const { data } = await client.get<QueryResponse<ErrorEventRow>>("/errors/query", { params });
  return data;
}

export interface UsersListParams {
  from: string;
  to: string;
  page: number;
  page_size: number;
}

export async function listUsers(params: UsersListParams): Promise<QueryResponse<UserSummary>> {
  const { data } = await client.get<QueryResponse<UserSummary>>("/users/list", { params });
  return data;
}

export interface UserVisitsParams {
  from: string;
  to: string;
  page: number;
  page_size: number;
}

export async function userVisits(email: string, params: UserVisitsParams): Promise<QueryResponse<AccessEventRow>> {
  const encoded = encodeURIComponent(email);
  const { data } = await client.get<QueryResponse<AccessEventRow>>(`/users/${encoded}/visits`, { params });
  return data;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>("/health");
  return data;
}

export async function geoipBatch(ips: string[]): Promise<Record<string, GeoIPItem>> {
  const { data } = await client.post<{ items: Record<string, GeoIPItem> }>("/geoip/batch", { ips });
  return data.items || {};
}

export async function authLogin(
  username: string,
  password: string
): Promise<{ username: string; expires_in: number; must_change_password?: boolean }> {
  const { data } = await client.post<{ username: string; expires_in: number; must_change_password?: boolean }>(
    "/auth/login",
    {
      username,
      password,
    }
  );
  return data;
}

export async function authLogout(): Promise<void> {
  await client.post("/auth/logout");
}

export async function authMe(): Promise<AuthMe> {
  const { data } = await client.get<AuthMe>("/auth/me");
  return data;
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await client.post("/auth/change-password", {
    old_password: oldPassword,
    new_password: newPassword,
  });
}

export async function getConfigSchema(): Promise<RuntimeConfigSchemaItem[]> {
  const { data } = await client.get<{ items: RuntimeConfigSchemaItem[] }>("/config/schema");
  return data.items || [];
}

export async function getConfigCurrent(): Promise<RuntimeConfigCurrentItem[]> {
  const { data } = await client.get<{ items: RuntimeConfigCurrentItem[] }>("/config/current");
  return data.items || [];
}

export async function updateConfigCurrent(items: Record<string, unknown>): Promise<RuntimeConfigCurrentItem[]> {
  const { data } = await client.put<{ items: RuntimeConfigCurrentItem[] }>("/config/current", { items });
  return data.items || [];
}

export async function getConfigHistory(
  page: number,
  page_size: number
): Promise<QueryResponse<RuntimeConfigHistoryItem>> {
  const { data } = await client.get<QueryResponse<RuntimeConfigHistoryItem>>("/config/history", {
    params: { page, page_size },
  });
  return data;
}
