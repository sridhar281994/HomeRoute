import DISTRICTS_TOWNS, { DistrictsTowns } from "./districtsTowns";

export function getDistricts(data: DistrictsTowns = DISTRICTS_TOWNS): string[] {
  return Object.keys(data || {}).filter(Boolean).sort((a, b) => a.localeCompare(b));
}

export function getStatesForDistrict(district: string, data: DistrictsTowns = DISTRICTS_TOWNS): string[] {
  const d = (data || {})[district] || {};
  return Object.keys(d).filter(Boolean).sort((a, b) => a.localeCompare(b));
}

export function getAreas(district: string, state: string, data: DistrictsTowns = DISTRICTS_TOWNS): string[] {
  const s = ((data || {})[district] || {})[state] || [];
  return (s || []).map(String).filter(Boolean).sort((a, b) => a.localeCompare(b));
}

export function isValidAreaSelection(district: string, state: string, area: string, data: DistrictsTowns = DISTRICTS_TOWNS): boolean {
  if (!district || !state || !area) return false;
  const areas = getAreas(district, state, data);
  return areas.includes(area);
}

export async function getBrowserGps(options?: { timeoutMs?: number }): Promise<{ lat: number; lon: number }> {
  const timeoutMs = options?.timeoutMs ?? 8000;
  return await new Promise((resolve, reject) => {
    if (!navigator.geolocation) return reject(new Error("GPS not supported in this browser/device."));
    let done = false;
    const t = window.setTimeout(() => {
      if (done) return;
      done = true;
      reject(new Error("GPS timeout. Please enable location and try again."));
    }, timeoutMs);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        if (done) return;
        done = true;
        window.clearTimeout(t);
        resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      (err) => {
        if (done) return;
        done = true;
        window.clearTimeout(t);
        reject(new Error(err?.message || "GPS permission denied."));
      },
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 30_000 }
    );
  });
}

