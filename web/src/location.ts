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

