export type User = {
  id: number;
  email: string;
  name: string;
  role: string;
  username?: string;
  phone?: string;
  owner_category?: string;
  image_url?: string;
  locations?: string[];
};

export type Session = {
  token: string;
  user?: User;
};

const KEY = "pd_session_v1";

export function getSession(): Session {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return { token: "" };
  }
}

export function setSession(s: Session) {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function clearSession() {
  localStorage.removeItem(KEY);
}

export const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const s = getSession();
  const headers = new Headers(init?.headers || {});
  headers.set("Accept", "application/json");
  if (s.token) headers.set("Authorization", `Bearer ${s.token}`);
  const resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) throw new Error(data?.detail || data?.message || `HTTP ${resp.status}`);
  return data as T;
}

export function registerUser(input: {
  email: string;
  phone: string;
  password: string;
  name: string;
  state: string;
  district: string;
  role: string;
  owner_category?: string;
}) {
  return api<{ ok: boolean; user_id: number }>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email: input.email,
      phone: input.phone,
      username: input.phone, // keep server-side uniqueness/compatibility
      password: input.password,
      name: input.name,
      state: input.state,
      district: input.district,
      role: input.role,
      owner_category: input.owner_category || "",
    }),
  });
}

export function requestOtp(identifier: string, password: string) {
  return api<{ ok: boolean; message: string }>("/auth/login/request-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password }),
  });
}

export function verifyOtp(identifier: string, password: string, otp: string) {
  return api<{ access_token: string; user: any }>("/auth/login/verify-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password, otp }),
  });
}

export function listProperties(params: { q?: string; rent_sale?: string; property_type?: string; max_price?: string }) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.rent_sale) sp.set("rent_sale", params.rent_sale);
  if (params.property_type) sp.set("property_type", params.property_type);
  if (params.max_price) sp.set("max_price", params.max_price);
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/properties${qs}`);
}

export function getProperty(id: number) {
  return api<any>(`/properties/${id}`);
}

export function getContact(id: number) {
  return api<any>(`/properties/${id}/contact`);
}

export function subscriptionStatus() {
  return api<{ status: string }>(`/me/subscription`);
}

export function ownerCreateProperty(input: any) {
  return api<{ id: number; status: string }>(`/owner/properties`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function uploadPropertyImage(propertyId: number, file: File, sortOrder = 0) {
  const s = getSession();
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${API_BASE}/properties/${propertyId}/images?sort_order=${sortOrder}`, {
    method: "POST",
    headers: s.token ? { Authorization: `Bearer ${s.token}` } : undefined,
    body: form,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
  return data;
}

export function adminPending() {
  return api<{ items: any[] }>(`/admin/properties/pending`);
}

export function adminApprove(id: number) {
  return api<{ ok: boolean }>(`/admin/properties/${id}/approve`, { method: "POST" });
}

export function adminReject(id: number) {
  return api<{ ok: boolean }>(`/admin/properties/${id}/reject`, { method: "POST" });
}

