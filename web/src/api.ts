export type User = {
  id: number;
  email: string;
  name: string;
  role: string;
  username?: string;
  phone?: string;
  owner_category?: string;
  // New backend field (preferred)
  profile_image_url?: string;
  // Legacy/local field (older UI stored this client-side)
  image_url?: string;
  locations?: string[];
};

export type Session = {
  token: string;
  user?: User;
};

export type CategoryCatalog = {
  version: string;
  updated: string;
  categories: Array<{ group: string; items: string[] }>;
  owner_categories: string[];
  flat_items: Array<{ id: string; label: string; group_id: string; group: string; search: string }>;
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

const _envBase: string | undefined = (import.meta as any).env?.VITE_API_BASE_URL;
const _defaultBase: string = (import.meta as any).env?.DEV ? "http://127.0.0.1:8000" : "";
export const API_BASE = String(_envBase ?? _defaultBase).replace(/\/+$/, "");

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const s = getSession();
  const headers = new Headers(init?.headers || {});
  headers.set("Accept", "application/json");
  if (s.token) headers.set("Authorization", `Bearer ${s.token}`);
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new Error(`Network error (cannot reach API). Check API URL/CORS. Tried: ${(API_BASE || window.location.origin) + path}`);
  }
  const text = await resp.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
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

export function adminLogin(identifier: string, password: string) {
  return api<{ access_token: string; user: any }>("/admin/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, password }),
  });
}

export function forgotPasswordRequestOtp(identifier: string) {
  return api<{ ok: boolean; message: string }>("/auth/forgot/request-otp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier }),
  });
}

export function forgotPasswordReset(identifier: string, otp: string, new_password: string) {
  return api<{ ok: boolean }>("/auth/forgot/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, otp, new_password }),
  });
}

export function listProperties(params: {
  q?: string;
  rent_sale?: string;
  property_type?: string;
  max_price?: string;
  state?: string;
  district?: string;
  sort_budget?: string;
}) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.rent_sale) sp.set("rent_sale", params.rent_sale);
  if (params.property_type) sp.set("property_type", params.property_type);
  if (params.max_price) sp.set("max_price", params.max_price);
  // Location is mandatory for guest browsing; backend enforces this too.
  if (params.state) sp.set("state", params.state);
  if (params.district) sp.set("district", params.district);
  if (params.sort_budget) sp.set("sort_budget", params.sort_budget);
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

export function getMe() {
  return api<{ user: User }>(`/me`);
}

export function updateMe(input: { name: string }) {
  return api<{ ok: boolean; user: User }>(`/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name }),
  });
}

export async function uploadProfileImage(file: File) {
  const s = getSession();
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${API_BASE}/me/profile-image`, {
    method: "POST",
    headers: s.token ? { Authorization: `Bearer ${s.token}` } : undefined,
    body: form,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
  return data as { ok: boolean; user: User };
}

export function requestChangeEmailOtp(new_email: string) {
  return api<{ ok: boolean; message: string }>(`/me/change-email/request-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_email }),
  });
}

export function verifyChangeEmailOtp(new_email: string, otp: string) {
  return api<{ ok: boolean; user: User }>(`/me/change-email/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_email, otp }),
  });
}

export function requestChangePhoneOtp(new_phone: string) {
  return api<{ ok: boolean; message: string }>(`/me/change-phone/request-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_phone }),
  });
}

export function verifyChangePhoneOtp(new_phone: string, otp: string) {
  return api<{ ok: boolean; user: User }>(`/me/change-phone/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_phone, otp }),
  });
}

export function deleteAccount() {
  return api<{ ok: boolean }>(`/me`, { method: "DELETE" });
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

export function adminSuspend(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/properties/${id}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminOwnersPending() {
  return api<{ items: any[] }>(`/admin/owners/pending`);
}

export function adminOwnerApprove(id: number) {
  return api<{ ok: boolean }>(`/admin/owners/${id}/approve`, { method: "POST" });
}

export function adminOwnerReject(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/owners/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminOwnerSuspend(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/owners/${id}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminImagesPending() {
  return api<{ items: any[] }>(`/admin/images/pending`);
}

export function adminImageApprove(id: number) {
  return api<{ ok: boolean }>(`/admin/images/${id}/approve`, { method: "POST" });
}

export function adminImageReject(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/images/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminImageSuspend(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/images/${id}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function getCategoryCatalog() {
  return api<CategoryCatalog>(`/meta/categories`);
}

