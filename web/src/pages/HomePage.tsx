import { useEffect, useMemo, useState } from "react";
import {
  getCategoryCatalog,
  getMe,
  getSession,
  listLocationAreas,
  listLocationDistricts,
  listLocationStates,
  listNearbyProperties,
  listProperties,
  toApiUrl,
  getContact,
} from "../api";
import { getBrowserGps } from "../location";

export default function HomePage() {
  const [need, setNeed] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [state, setState] = useState<string>(() => {
    const s = getSession();
    const fromProfile = String((s.user as any)?.state || "").trim();
    return fromProfile || localStorage.getItem("pd_state") || "";
  });
  const [district, setDistrict] = useState<string>(() => {
    const s = getSession();
    const fromProfile = String((s.user as any)?.district || "").trim();
    return fromProfile || localStorage.getItem("pd_district") || "";
  });
  const [area, setArea] = useState<string>(() => localStorage.getItem("pd_area") || "");
  const [radiusKm, setRadiusKm] = useState<string>(() => localStorage.getItem("pd_radius_km") || "20");
  const [sortBudget, setSortBudget] = useState<string>("");
  const [postedWithinDays, setPostedWithinDays] = useState<string>("");
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string>("");
  const [gps, setGps] = useState<{ lat: number; lon: number } | null>(null);
  const [catalog, setCatalog] = useState<any>(null);
  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [districtOptions, setDistrictOptions] = useState<string[]>([]);
  const [areaOptions, setAreaOptions] = useState<string[]>([]);
  const [contacted, setContacted] = useState<Record<number, boolean>>({});
  const [contactMsg, setContactMsg] = useState<Record<number, string>>({});
  const [didAutoLoad, setDidAutoLoad] = useState<boolean>(false);

  const needGroups = useMemo(() => {
    const cats = (catalog?.categories || []) as Array<{ group: string; items: string[] }>;
    return cats
      .map((g) => ({ group: String(g.group || "").trim(), items: (g.items || []).map((x) => String(x || "").trim()).filter(Boolean) }))
      .filter((g) => g.group && g.items.length);
  }, [catalog]);

  async function load() {
    setErr("");
    try {
      const q = (need || "").trim() || undefined;
      const radius = Number(radiusKm || 0) || 20;

      // If GPS is available, show nearby ads by distance; otherwise fall back to non-GPS listing.
      const res = gps
        ? await listNearbyProperties({
            lat: gps.lat,
            lon: gps.lon,
            radius_km: radius,
            district: district || undefined,
            state: state || undefined,
            area: area || undefined,
            q,
            max_price: maxPrice || undefined,
            rent_sale: rentSale || undefined,
            property_type: undefined,
            posted_within_days: postedWithinDays || undefined,
            limit: 60,
          })
        : await listProperties({
            q,
            max_price: maxPrice || undefined,
            rent_sale: rentSale || undefined,
            district: district || undefined,
            state: state || undefined,
            area: area || undefined,
            sort_budget: sortBudget || undefined,
            posted_within_days: postedWithinDays || undefined,
          });
      setItems(res.items || []);
    } catch (e: any) {
      setErr(e.message || "Failed");
    }
  }

  useEffect(() => {
    // Auto-load once when default state+district are known.
    if (didAutoLoad) return;
    if (!(state || "").trim() || !(district || "").trim()) return;
    setDidAutoLoad(true);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [didAutoLoad, state, district]);

  useEffect(() => {
    // If GPS becomes available after the first load, reload once to show nearby + distance info.
    if (!didAutoLoad) return;
    if (!gps) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gps, didAutoLoad]);

  useEffect(() => {
    (async () => {
      try {
        const r = await listLocationStates();
        setStateOptions((r.items || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        // Non-fatal: keep dropdown empty if API is unreachable.
        setStateOptions([]);
      }
    })();
  }, []);

  useEffect(() => {
    // Default state/district from user profile (if logged-in). Also avoid leaking location filters across users.
    (async () => {
      try {
        const s = getSession();
        if (!s.token) return;

        const userId = (s.user as any)?.id;
        const prevUserId = localStorage.getItem("pd_user_id");
        if (userId != null && prevUserId !== String(userId)) {
          localStorage.setItem("pd_user_id", String(userId));
          localStorage.removeItem("pd_state");
          localStorage.removeItem("pd_district");
          localStorage.removeItem("pd_area");
          setState("");
          setDistrict("");
          setArea("");
        }

        // Prefer live profile (server is source of truth).
        const me = await getMe();
        const u: any = me.user || {};
        const st = String(u.state || "").trim();
        const dist = String(u.district || "").trim();
        if (st && !(state || "").trim()) setState(st);
        if (dist && !(district || "").trim()) setDistrict(dist);
      } catch {
        // ignore
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!state) {
      setDistrictOptions([]);
      setDistrict("");
      setAreaOptions([]);
      setArea("");
      return;
    }
    (async () => {
      try {
        const r = await listLocationDistricts(state);
        setDistrictOptions((r.items || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        setDistrictOptions([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  useEffect(() => {
    if (!state || !district) {
      setAreaOptions([]);
      setArea("");
      return;
    }
    (async () => {
      try {
        const r = await listLocationAreas(state, district);
        setAreaOptions((r.items || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        setAreaOptions([]);
      }
    })();
  }, [state, district]);

  useEffect(() => {
    (async () => {
      try {
        const c = await getCategoryCatalog();
        setCatalog(c);
      } catch {
        // Non-fatal: search still works without category metadata.
      }
    })();
  }, []);

  useEffect(() => {
    localStorage.setItem("pd_state", state || "");
  }, [state]);

  useEffect(() => {
    localStorage.setItem("pd_district", district || "");
  }, [district]);

  useEffect(() => {
    localStorage.setItem("pd_area", area || "");
  }, [area]);

  useEffect(() => {
    localStorage.setItem("pd_radius_km", radiusKm || "");
  }, [radiusKm]);

  useEffect(() => {
    // Capture GPS once so we can auto-show nearby ads.
    (async () => {
      try {
        const p = await getBrowserGps({ timeoutMs: 8000 });
        setGps(p);
      } catch (e: any) {
        // Non-fatal: user can still browse without GPS, but proximity sorting won't be available.
        // Don't hard-fail the page; keep browsing working.
      }
    })();
  }, []);

  function fmtDistance(dkm: any): string {
    const n = Number(dkm);
    if (!Number.isFinite(n)) return "";
    const pretty = n < 10 ? n.toFixed(1) : Math.round(n).toString();
    return `${pretty}km from you`;
  }

  return (
    <div className="page-home">
      <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          <span className="muted">Uncover the best, Good Luck</span>
        </p>
        <div className="spacer" />
        <button onClick={load}>Refresh</button>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">State (optional)</label>
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setDistrict("");
              setArea("");
            }}
          >
            <option value="">Any</option>
            {stateOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">District (optional)</label>
          <select
            value={district}
            onChange={(e) => {
              setDistrict(e.target.value);
              setArea("");
            }}
            disabled={!state}
          >
            <option value="">{state ? "Any" : "Any"}</option>
            {districtOptions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Area (optional)</label>
          <select value={area} onChange={(e) => setArea(e.target.value)} disabled={!state || !district}>
            <option value="">{state && district ? "Any" : "Any"}</option>
            {areaOptions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          {area && areaOptions.length && !areaOptions.includes(area) ? <div className="muted" style={{ marginTop: 6 }}>Invalid area selection.</div> : null}
        </div>
        <div className="col-6">
          <label className="muted">Nearby radius (km)</label>
          <input value={radiusKm} onChange={(e) => setRadiusKm(e.target.value)} inputMode="numeric" />
          <div className="muted" style={{ marginTop: 6 }}>
            {gps ? `Using GPS (${gps.lat.toFixed(4)}, ${gps.lon.toFixed(4)})` : "GPS not available (showing non-nearby results)."}
          </div>
        </div>
        <div className="col-6">
          <label className="muted">Need category (materials / services / property)</label>
          <select value={need} onChange={(e) => setNeed(e.target.value)}>
            <option value="">Any</option>
            {needGroups.map((g) => (
              <optgroup key={g.group} label={g.group}>
                {g.items.map((it) => (
                  <option key={`${g.group}:${it}`} value={it}>
                    {it}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Post date</label>
          <select value={postedWithinDays} onChange={(e) => setPostedWithinDays(e.target.value)}>
            <option value="">Any</option>
            <option value="1">Today</option>
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Sort (by budget)</label>
          <select value={sortBudget} onChange={(e) => setSortBudget(e.target.value)}>
            <option value="">Any (Newest)</option>
            <option value="top">Top (high to low)</option>
            <option value="bottom">Bottom (low to high)</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Max budget</label>
          <input value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Rent/Sale</label>
          <select value={rentSale} onChange={(e) => setRentSale(e.target.value)}>
            <option value="">Any</option>
            <option value="rent">Rent</option>
            <option value="sale">Sale</option>
          </select>
        </div>
        <div className="col-12 row">
          <button className="primary" onClick={load}>
            Apply filters
          </button>
          <span className="muted">{err}</span>
        </div>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        {items.map((p) => (
          <div className="col-12" key={p.id}>
            <div className="card post-card">
              <div className="post-header">
                <div className="post-avatar" aria-hidden="true">
                  {String(p.owner_company_name || p.owner_name || p.title || "A").trim().slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <div className="h2" style={{ margin: 0 }}>
                    {p.title}
                  </div>
                  <div className="muted post-meta">
                    {p.distance_km != null ? `${fmtDistance(p.distance_km)} • ` : ""}
                    Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} • {p.rent_sale} • {p.property_type} • {p.price_display} •{" "}
                    {p.location_display}
                    {p.created_at ? ` • ${new Date(p.created_at).toLocaleDateString()}` : ""}
                  </div>
                </div>
                <div className="spacer" />
              </div>

              <div className="post-body">
                <div className="h2" style={{ marginTop: 6 }}>
                  Photos
                </div>
                {p.images?.length ? (
                <div className="post-media">
                  <div className="grid" style={{ marginTop: 10 }}>
                    {p.images.slice(0, 6).map((i: any) => (
                      <div className="col-6" key={i.id ?? i.url}>
                        {String(i.content_type || "").toLowerCase().startsWith("video/") ? (
                          <video controls preload="metadata" src={toApiUrl(i.url)} style={{ width: "100%", height: 220, objectFit: "cover", borderRadius: 14 }} />
                        ) : (
                          <img src={toApiUrl(i.url)} alt={`Ad ${p.id} media`} loading="lazy" style={{ width: "100%", height: 220, objectFit: "cover", borderRadius: 14 }} />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
                ) : (
                  <div className="muted" style={{ marginTop: 6 }}>
                    No photos.
                  </div>
                )}

                <div className="h2" style={{ marginTop: 12 }}>
                  Amenities
                </div>
                <div className="muted" style={{ marginTop: 6 }}>
                  {p.amenities?.length ? p.amenities.join(", ") : "—"}
                </div>

                <div className="row" style={{ marginTop: 12, alignItems: "center" }}>
                  <button
                    className="primary"
                    disabled={!!contacted[Number(p.id)]}
                    onClick={async () => {
                      const pid = Number(p.id);
                      setContactMsg((m) => ({ ...m, [pid]: "" }));
                      try {
                        const contact = await getContact(pid);
                        const ownerName = String(contact.owner_name || "").trim();
                        const advNo = String(contact.adv_number || contact.advNo || p.adv_number || p.ad_number || p.id || "").trim();
                        const sent = "Contact details sent to your registered email/SMS.";
                        const who = ownerName ? ` (${ownerName})` : "";
                        const label = advNo ? ` Ad #${advNo}${who}.` : ` Ad${who}.`;
                        setContacted((c) => ({ ...c, [pid]: true }));
                        setContactMsg((m) => ({ ...m, [pid]: `${sent}${label}`.trim() }));
                      } catch (e: any) {
                        setContactMsg((m) => ({ ...m, [pid]: e.message || "Locked" }));
                      }
                    }}
                  >
                    {contacted[Number(p.id)] ? "Contacted" : "Contact owner"}
                  </button>
                  <span className="muted">{contactMsg[Number(p.id)] || ""}</span>
                </div>
              </div>
            </div>
          </div>
        ))}
        {!items.length ? (
          <div className="col-12 muted" style={{ marginTop: 8 }}>
            No Upload yet thanks for reaching us.
          </div>
        ) : null}
      </div>
      </div>
    </div>
  );
}

