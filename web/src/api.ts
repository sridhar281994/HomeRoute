export type User = {
  id: number;
  email: string;
  name: string;
  role: string;
  username?: string;
  phone?: string;
  owner_category?: string;
  company_name?: string;
  // New backend field (preferred)
  profile_image_url?: string;
  // Legacy/local field (older UI stored this client-side)
  image_url?: string;
  locations?: string[];
};

export type Session = {
  token: string;
  user?: User;
  guest?: boolean;
};

export type CategoryCatalog = {
  version: string;
  updated: string;
  categories: Array<{ group: string; items: string[] }>;
  owner_categories: string[];
  flat_items: Array<{ id: string; label: string; group_id: string; group: string; search: string }>;
  warning?: string;
  source?: string;
};

const KEY = "pd_session_v1";

export function getSession(): Session {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}");
    const token = String(raw?.token || "");
    return { token, user: raw?.user, guest: Boolean(raw?.guest) && !token };
  } catch {
    return { token: "", guest: false };
  }
}

export function setSession(s: Session) {
  localStorage.setItem(KEY, JSON.stringify(s));
}

export function clearSession() {
  localStorage.removeItem(KEY);
}

export function setGuestSession() {
  setSession({
    token: "",
    user: { id: 0, email: "guest@local", name: "Guest", role: "guest" },
    guest: true,
  });
}

const _envBase: string | undefined = (import.meta as any).env?.VITE_API_BASE_URL;
const _prodDefaultBase = "https://homeroute-pt0c.onrender.com";
const _defaultBase: string = (import.meta as any).env?.DEV ? "http://127.0.0.1:8000" : _prodDefaultBase;
const _rawBase = String(_envBase ?? "").trim();
export const API_BASE = String(_rawBase || _defaultBase).replace(/\/+$/, "");

export function toApiUrl(url: string): string {
  const u = String(url || "").trim();
  if (!u) return "";
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  if (u.startsWith("//")) return u;
  // If web UI is served from same origin as API (prod build), API_BASE is "".
  if (!API_BASE) return u;
  if (u.startsWith("/")) return `${API_BASE}${u}`;
  return `${API_BASE}/${u}`;
}

export function formatPriceDisplay(value: any): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  if (/^rs\.?\s+/i.test(raw) || /^₹\s*/.test(raw)) return raw;
  return `Rs ${raw}`;
}

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

export function loginWithGoogle(id_token: string) {
  return api<{ access_token: string; user: any }>("/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token }),
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
  post_group?: string;
  max_price?: string;
  state?: string;
  district?: string;
  area?: string;
  sort_budget?: string;
  posted_within_days?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  if (params.q) sp.set("q", params.q);
  if (params.rent_sale) sp.set("rent_sale", params.rent_sale);
  if (params.property_type) sp.set("property_type", params.property_type);
  if (params.post_group) sp.set("post_group", params.post_group);
  if (params.max_price) sp.set("max_price", params.max_price);
  // Location filters are optional; pass them only when selected.
  if (params.state) sp.set("state", params.state);
  if (params.district) sp.set("district", params.district);
  if (params.area) sp.set("area", params.area);
  if (params.sort_budget) sp.set("sort_budget", params.sort_budget);
  if (params.posted_within_days) sp.set("posted_within_days", params.posted_within_days);
  if (params.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/properties${qs}`);
}

export function listNearbyProperties(params: {
  lat: number;
  lon: number;
  radius_km?: number;
  district?: string;
  state?: string;
  area?: string;
  q?: string;
  rent_sale?: string;
  property_type?: string;
  post_group?: string;
  max_price?: string;
  posted_within_days?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  sp.set("lat", String(params.lat));
  sp.set("lon", String(params.lon));
  if (params.radius_km != null) sp.set("radius_km", String(params.radius_km));
  if (params.district) sp.set("district", params.district);
  if (params.state) sp.set("state", params.state);
  if (params.area) sp.set("area", params.area);
  if (params.q) sp.set("q", params.q);
  if (params.rent_sale) sp.set("rent_sale", params.rent_sale);
  if (params.property_type) sp.set("property_type", params.property_type);
  if (params.post_group) sp.set("post_group", params.post_group);
  if (params.max_price) sp.set("max_price", params.max_price);
  if (params.posted_within_days) sp.set("posted_within_days", params.posted_within_days);
  if (params.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/properties/nearby${qs}`);
}

export function getProperty(id: number) {
  return api<any>(`/properties/${id}`);
}

export function getContact(id: number) {
  return api<any>(`/properties/${id}/contact`);
}

export function getMe() {
  return api<{ user: User }>(`/me`);
}

export function getSubscriptionStatus() {
  return api<{ status: string; provider?: string; expires_at?: string }>(`/me/subscription`);
}

export function getSubscriptionSummary(params?: { window_days?: number }) {
  const wd = params?.window_days ?? 30;
  return api<{
    window_days: number;
    from: string;
    to: string;
    service_requested: number;
    earned: number;
    merchant_fee: number;
    merchant_fee_rate: number;
  }>(`/me/subscription/summary?window_days=${encodeURIComponent(String(wd))}`);
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

export function ownerListProperties() {
  return api<{ items: any[] }>(`/owner/properties`);
}

export function ownerUpdateProperty(id: number, input: any) {
  return api<{ ok: boolean; property: any }>(`/owner/properties/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input || {}),
  });
}

export function ownerDeleteProperty(id: number) {
  return api<{ ok: boolean }>(`/owner/properties/${id}`, { method: "DELETE" });
}

export async function ownerPublishProperty(input: any, files: File[]) {
  const s = getSession();
  const form = new FormData();
  form.append("payload", JSON.stringify(input || {}));
  for (const f of files || []) {
    form.append("files", f);
  }
  const resp = await fetch(`${API_BASE}/owner/properties/publish`, {
    method: "POST",
    headers: s.token ? { Authorization: `Bearer ${s.token}` } : undefined,
    body: form,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data?.detail || `HTTP ${resp.status}`);
  return data;
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

export function adminListProperties(params?: {
  q?: string;
  rent_sale?: string;
  property_type?: string;
  max_price?: string;
  state?: string;
  district?: string;
  area?: string;
  status?: string;
  sort_budget?: string;
  posted_within_days?: string;
  limit?: number;
}) {
  const sp = new URLSearchParams();
  if (params?.q) sp.set("q", params.q);
  if (params?.rent_sale) sp.set("rent_sale", params.rent_sale);
  if (params?.property_type) sp.set("property_type", params.property_type);
  if (params?.max_price) sp.set("max_price", params.max_price);
  if (params?.state) sp.set("state", params.state);
  if (params?.district) sp.set("district", params.district);
  if (params?.area) sp.set("area", params.area);
  if (params?.status) sp.set("status", params.status);
  if (params?.sort_budget) sp.set("sort_budget", params.sort_budget);
  if (params?.posted_within_days) sp.set("posted_within_days", params.posted_within_days);
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/admin/properties${qs}`);
}

export function adminUpdateProperty(
  id: number,
  input: {
    title?: string | null;
    description?: string | null;
    property_type?: string | null;
    rent_sale?: string | null;
    price?: number | null;
    location?: string | null;
    state?: string | null;
    district?: string | null;
    area?: string | null;
    address?: string | null;
    amenities?: string[] | null;
    availability?: string | null;
    contact_phone?: string | null;
    contact_email?: string | null;
    company_name?: string | null;
    gps_lat?: number | null;
    gps_lng?: number | null;
  },
) {
  return api<{ ok: boolean; property: any }>(`/admin/properties/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input || {}),
  });
}

export function adminDeleteProperty(id: number) {
  return api<{ ok: boolean }>(`/admin/properties/${id}`, { method: "DELETE" });
}

export function adminApprove(id: number) {
  return api<{ ok: boolean }>(`/admin/properties/${id}/approve`, { method: "POST" });
}

export function adminReject(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/properties/${id}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminSuspend(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/properties/${id}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminMarkSpam(id: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/properties/${id}/spam`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminListUsers(params?: { q?: string; limit?: number }) {
  const sp = new URLSearchParams();
  if (params?.q) sp.set("q", params.q);
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/admin/users${qs}`);
}

export function adminGetUser(userId: number) {
  return api<{ user: any; total_posts: number; posts: any[] }>(`/admin/users/${userId}`);
}

export function adminSuspendUser(userId: number, reason = "") {
  return api<{ ok: boolean }>(`/admin/users/${userId}/suspend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
}

export function adminApproveUser(userId: number) {
  return api<{ ok: boolean }>(`/admin/users/${userId}/approve`, { method: "POST" });
}

export function adminDeleteUser(userId: number) {
  return api<{ ok: boolean; user_id: number; deleted_posts: number }>(`/admin/users/${userId}`, { method: "DELETE" });
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

export function adminLogs(params?: { entity_type?: string; entity_id?: number; limit?: number }) {
  const sp = new URLSearchParams();
  if (params?.entity_type) sp.set("entity_type", params.entity_type);
  if (params?.entity_id != null) sp.set("entity_id", String(params.entity_id));
  if (params?.limit != null) sp.set("limit", String(params.limit));
  const qs = sp.toString() ? `?${sp.toString()}` : "";
  return api<{ items: any[] }>(`/admin/logs${qs}`);
}

export function getCategoryCatalog() {
  return api<CategoryCatalog>(`/meta/categories`);
}

export function listLocationStates() {
  return api<{ items: string[] }>(`/locations/states`);
}

export function listLocationDistricts(state: string) {
  const sp = new URLSearchParams();
  sp.set("state", state);
  return api<{ items: string[] }>(`/locations/districts?${sp.toString()}`);
}

export function listLocationAreas(state: string, district: string) {
  const sp = new URLSearchParams();
  sp.set("state", state);
  sp.set("district", district);
  return api<{ items: string[] }>(`/locations/areas?${sp.toString()}`);
}

