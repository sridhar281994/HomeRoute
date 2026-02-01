import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  getCategoryCatalog,
  getMe,
  getSession,
  listLocationAreas,
  listLocationDistricts,
  listLocationStates,
  listNearbyProperties,
  listProperties,
  setSession,
  toApiUrl,
  getContact,
} from "../api";
import { getBrowserGps } from "../location";

export default function HomePage() {
  const nav = useNavigate();
  const session = getSession();
  const user: any = session.user || {};
  const profileImageUrl = String(user?.profile_image_url || "").trim();
  const avatarLetter = String(user?.name || user?.email || user?.phone || "U")
    .trim()
    .slice(0, 1)
    .toUpperCase() || "U";
  const [need, setNeed] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [state, setState] = useState<string>("");
  const [district, setDistrict] = useState<string>("");
  const [areas, setAreas] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem("pd_areas") || "";
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          return parsed.map((x) => String(x || "").trim()).filter(Boolean);
        }
      }
    } catch {
      // ignore
    }
    const legacy = String(localStorage.getItem("pd_area") || "").trim();
    return legacy ? [legacy] : [];
  });
  const [areaSearch, setAreaSearch] = useState<string>("");
  const [radiusKm, setRadiusKm] = useState<string>(() => localStorage.getItem("pd_radius_km") || "20");
  const [sortBudget, setSortBudget] = useState<string>("");
  const [postedWithinDays, setPostedWithinDays] = useState<string>("");
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string>("");
  const [categoryMsg, setCategoryMsg] = useState<string>("");
  const [locationMsg, setLocationMsg] = useState<string>("");
  const [profileState, setProfileState] = useState<string>(() => String((session.user as any)?.state || "").trim());
  const [profileDistrict, setProfileDistrict] = useState<string>(() => String((session.user as any)?.district || "").trim());
  const [gps, setGps] = useState<{ lat: number; lon: number } | null>(null);
  const [gpsMsg, setGpsMsg] = useState<string>("");
  const [catalog, setCatalog] = useState<any>(null);
  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [districtOptions, setDistrictOptions] = useState<string[]>([]);
  const [areaOptions, setAreaOptions] = useState<string[]>([]);
  const [contacted, setContacted] = useState<Record<number, boolean>>({});
  const [contactMsg, setContactMsg] = useState<Record<number, string>>({});
  const [didAutoLoad, setDidAutoLoad] = useState<boolean>(false);

  function isValidGps(p: { lat: number; lon: number } | null): p is { lat: number; lon: number } {
    if (!p) return false;
    const lat = Number(p.lat);
    const lon = Number(p.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
    if (Math.abs(lat) < 1e-6 && Math.abs(lon) < 1e-6) return false; // don't treat (0,0) as real GPS
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return false;
    return true;
  }

  function cleanGpsUiMessage(msg: any): string {
    const s = String(msg || "").trim();
    if (!s) return "GPS permission denied.";
    // Never show the browser's technical permissions-policy message in the UI.
    if (s.toLowerCase().includes("geolocation has been disabled in this document by permissions policy")) {
      return "GPS is blocked by browser policy.";
    }
    if (s.toLowerCase().includes("only secure origins are allowed")) {
      return "GPS requires HTTPS (secure site).";
    }
    return s;
  }

  const needGroups = useMemo(() => {
    const cats = (catalog?.categories || []) as Array<{ group: string; items: string[] }>;
    const grouped = cats
      .map((g) => ({ group: String(g.group || "").trim(), items: (g.items || []).map((x) => String(x || "").trim()).filter(Boolean) }))
      .filter((g) => g.group && g.items.length);
    if (grouped.length) return grouped;

    const flat = (catalog?.flat_items || []) as Array<{ group: string; label: string }>;
    if (!flat.length) return [];
    const byGroup: Record<string, string[]> = {};
    for (const it of flat) {
      const group = String(it.group || "").trim() || "General";
      const label = String(it.label || "").trim();
      if (!label) continue;
      (byGroup[group] ||= []).push(label);
    }
    return Object.entries(byGroup).map(([group, items]) => ({ group, items }));
  }, [catalog]);
  const needOptionsFlat = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const g of needGroups) {
      for (const it of g.items) {
        const v = String(it || "").trim();
        const k = v.toLowerCase();
        if (!v || seen.has(k)) continue;
        seen.add(k);
        out.push(v);
      }
    }
    return out.sort((a, b) => a.localeCompare(b));
  }, [needGroups]);
  const categoryHint = categoryMsg || (needGroups.length ? "" : "Categories unavailable.");

  async function load() {
    setErr("");
    try {
      const q = (need || "").trim() || undefined;
      const radiusNum = parseInt(String(radiusKm || "").trim(), 10);
      const radius = Number.isFinite(radiusNum) && radiusNum > 0 ? radiusNum : 20;
      const gpsOk = isValidGps(gps);
      const maxPriceTrim = String(maxPrice || "").trim();
      const maxPriceParam = /^\d+$/.test(maxPriceTrim) ? maxPriceTrim : undefined;

      // If GPS is available, show nearby ads by distance; otherwise fall back to non-GPS listing.
      const res = gpsOk
        ? await listNearbyProperties({
            lat: gps.lat,
            lon: gps.lon,
            radius_km: radius,
            district: district || undefined,
            state: state || undefined,
            area: areas.length ? areas.join(",") : undefined,
            q,
            max_price: maxPriceParam,
            rent_sale: rentSale || undefined,
            property_type: undefined,
            posted_within_days: postedWithinDays || undefined,
            limit: 20,
          })
        : await listProperties({
            q,
            max_price: maxPriceParam,
            rent_sale: rentSale || undefined,
            district: district || undefined,
            state: state || undefined,
            area: areas.length ? areas.join(",") : undefined,
            sort_budget: sortBudget || undefined,
            posted_within_days: postedWithinDays || undefined,
            limit: 20,
          });
      const nextItems = res.items || [];
      setItems(nextItems);
      const currentSession = getSession();
      if (currentSession.token) {
        const nextContacted: Record<number, boolean> = {};
        for (const item of nextItems) {
          const pid = Number(item.id);
          if (Number.isFinite(pid) && item.contacted) {
            nextContacted[pid] = true;
          }
        }
        setContacted(nextContacted);
      } else {
        setContacted({});
      }
    } catch (e: any) {
      setErr(e.message || "Failed");
    }
  }

  async function requestGps() {
    try {
      const p = await getBrowserGps({ timeoutMs: 8000 });
      if (isValidGps(p)) {
        setGps(p);
        setGpsMsg("");
      } else {
        // Avoid ever displaying or using (0,0) GPS.
        setGps(null);
        setGpsMsg("GPS not available.");
      }
    } catch (e: any) {
      setGpsMsg(cleanGpsUiMessage(e?.message || e));
    }
  }

  useEffect(() => {
    // Auto-load once with "Any" defaults (no location filter).
    if (didAutoLoad) return;
    setDidAutoLoad(true);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [didAutoLoad]);

  useEffect(() => {
    // If GPS becomes available after the first load, reload once to show nearby + distance info.
    if (!didAutoLoad) return;
    if (!isValidGps(gps)) return;
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
    if (!session.token) return;
    (async () => {
      try {
        const r = await getMe();
        const u = r.user as any;
        setProfileState(String(u.state || "").trim());
        setProfileDistrict(String(u.district || "").trim());
        setSession({ token: session.token, user: u });
      } catch (e: any) {
        setLocationMsg(e.message || "Failed to load profile location.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.token]);

  useEffect(() => {
    // Avoid leaking location filters across users; keep "Any" as default.
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
          localStorage.removeItem("pd_areas");
          setState("");
          setDistrict("");
          setAreas([]);
        }
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
      setAreas([]);
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
    if (!profileState || state) return;
    if (stateOptions.includes(profileState)) {
      setState(profileState);
    } else if (stateOptions.length && !locationMsg) {
      setLocationMsg(`Saved state "${profileState}" is not available.`);
    }
  }, [profileState, stateOptions, state, locationMsg]);

  useEffect(() => {
    if (!state || !district) {
      setAreaOptions([]);
      setAreas([]);
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
    if (!profileDistrict || district) return;
    if (districtOptions.includes(profileDistrict)) {
      setDistrict(profileDistrict);
    } else if (districtOptions.length && !locationMsg) {
      setLocationMsg(`Saved district "${profileDistrict}" is not available.`);
    }
  }, [profileDistrict, districtOptions, district, locationMsg]);

  useEffect(() => {
    (async () => {
      try {
        const c = await getCategoryCatalog();
        setCatalog(c);
        const warn = String((c as any)?.warning || "").trim();
        setCategoryMsg(warn);
      } catch {
        // Non-fatal: search still works without category metadata.
        setCategoryMsg("Categories unavailable. Check API /meta/categories.");
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
    try {
      localStorage.setItem("pd_areas", JSON.stringify(areas || []));
      // Keep legacy single-value key for backward compatibility.
      localStorage.setItem("pd_area", String(areas?.[0] || ""));
    } catch {
      // ignore
    }
  }, [areas]);

  useEffect(() => {
    localStorage.setItem("pd_radius_km", radiusKm || "");
  }, [radiusKm]);

  useEffect(() => {
    // Capture GPS once so we can auto-show nearby ads.
    requestGps();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
          <span className="home-tagline">Uncover the Best, Good Luck</span>
        </p>
        <div className="spacer" />
        <button
          onClick={() => {
            const s = getSession();
            if (!s.token) {
              nav("/login");
              return;
            }
            nav("/subscription");
          }}
        >
          Subscription
        </button>
        <button onClick={load}>Refresh</button>
        <button
          type="button"
          title="Profile"
          aria-label="Profile"
          onClick={() => nav("/profile")}
          style={{
            width: 44,
            height: 44,
            borderRadius: 999,
            padding: 0,
            overflow: "hidden",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            border: "1px solid rgba(255,255,255,.18)",
            background: "rgba(0,0,0,.20)",
          }}
        >
          {profileImageUrl ? (
            <img
              src={toApiUrl(profileImageUrl)}
              alt="Profile"
              style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
            />
          ) : (
            <span style={{ fontWeight: 800 }}>{avatarLetter}</span>
          )}
        </button>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">State (optional)</label>
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setDistrict("");
              setAreas([]);
              setAreaSearch("");
            }}
          >
            <option value="">Any</option>
            {stateOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {locationMsg ? <div className="muted" style={{ marginTop: 6 }}>{locationMsg}</div> : null}
        </div>
        <div className="col-6">
          <label className="muted">District (optional)</label>
          <select
            value={district}
            onChange={(e) => {
              setDistrict(e.target.value);
              setAreas([]);
              setAreaSearch("");
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
          <input
            value={areaSearch}
            onChange={(e) => setAreaSearch(e.target.value)}
            disabled={!state || !district}
            placeholder={state && district ? "Search areas…" : "Select State + District first"}
          />
          <div className="multi-select" style={{ marginTop: 8, opacity: !state || !district ? 0.6 : 1 }}>
            {(areaOptions || [])
              .filter((a) => a && a !== "Any")
              .filter((a) => {
                const q = String(areaSearch || "").trim().toLowerCase();
                return !q || a.toLowerCase().includes(q);
              })
              .slice(0, 80)
              .map((a) => {
                const checked = areas.includes(a);
                const toggle = () =>
                  setAreas((prev) => {
                    const has = prev.includes(a);
                    if (has) return prev.filter((x) => x !== a);
                    return [...prev, a];
                  });
                return (
                  <div
                    key={a}
                    className={`multi-row ${checked ? "multi-on" : ""}`}
                    role="button"
                    tabIndex={0}
                    onClick={toggle}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") toggle();
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle()}
                      onClick={(e) => e.stopPropagation()}
                      disabled={!state || !district}
                    />
                    <span>{a}</span>
                  </div>
                );
              })}
            {!state || !district ? <div className="muted">Select State + District to load Areas.</div> : null}
            {state && district && !areaOptions.length ? <div className="muted">No areas found.</div> : null}
          </div>
          <div className="row" style={{ marginTop: 8, gap: 10, alignItems: "center" }}>
            <button
              onClick={() => {
                setAreas([]);
                setAreaSearch("");
              }}
              disabled={!areas.length}
            >
              Clear Areas
            </button>
            <div className="muted">{areas.length ? `${areas.length} selected` : "Any"}</div>
          </div>
          {areas.length ? (
            <div className="chips" style={{ marginTop: 8 }}>
              {areas.slice(0, 12).map((a) => (
                <button key={a} className="chipx" onClick={() => setAreas((prev) => prev.filter((x) => x !== a))}>
                  {a} ✕
                </button>
              ))}
              {areas.length > 12 ? <span className="muted">+{areas.length - 12} more</span> : null}
            </div>
          ) : null}
        </div>
        <div className="col-6">
          <label className="muted">Nearby radius (km)</label>
          <input value={radiusKm} onChange={(e) => setRadiusKm(e.target.value)} inputMode="numeric" />
          <div className="muted" style={{ marginTop: 6 }}>
            {isValidGps(gps) ? "GPS enabled (showing nearby results)." : "GPS not available (showing non-nearby results)."}
          </div>
          <div className="row" style={{ marginTop: 6, alignItems: "center" }}>
            <button onClick={requestGps}>Enable GPS</button>
            <span className="muted">{gpsMsg}</span>
          </div>
        </div>
        <div className="col-6">
          <label className="muted">Need category (materials / services / property)</label>
          <input
            value={need}
            onChange={(e) => setNeed(e.target.value)}
            placeholder="Any / type to search…"
            list="need-category-list"
          />
          <datalist id="need-category-list">
            {needOptionsFlat.map((it) => (
              <option key={it} value={it} />
            ))}
          </datalist>
          {categoryHint ? <div className="muted" style={{ marginTop: 6 }}>{categoryHint}</div> : null}
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
        {items.map((p) => {
          const pid = Number(p.id);
          const pidKey = Number.isInteger(pid) ? pid : Number.NaN;
          const amenities = Array.isArray(p.amenities)
            ? p.amenities
                .map((a: any) => String(a).trim())
                .filter((v) => {
                  const s = String(v || "").trim();
                  if (!s) return false;
                  const lc = s.toLowerCase();
                  if (s === "—" || s === "-") return false;
                  if (lc === "none") return false;
                  // Hide accidental values like "Amenities—"
                  if (lc.startsWith("amenities")) return false;
                  return true;
                })
            : [];
          return (
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
                    <div className="post-media placeholder" aria-hidden="true">
                      <div className="media-placeholder" />
                      <div className="media-placeholder" />
                      <div className="muted" style={{ gridColumn: "1 / -1", textAlign: "center" }}>
                        No Photos
                      </div>
                    </div>
                  )}

                  {amenities.length ? (
                    <div className="muted" style={{ marginTop: 12 }}>
                      {amenities.join(", ")}
                    </div>
                  ) : null}

                  <div className="row" style={{ marginTop: 12, alignItems: "center" }}>
                    <button
                      className="primary"
                      disabled={!!contacted[pidKey] || !!p.contacted}
                      onClick={async () => {
                        if (!Number.isInteger(pid) || pid <= 0) {
                          setContactMsg((m) => ({ ...m, [pidKey]: "Invalid ad id." }));
                          return;
                        }
                        const s = getSession();
                        if (!s.token) {
                          setContactMsg((m) => ({ ...m, [pidKey]: "Login required to contact owner." }));
                          nav("/login");
                          return;
                        }
                        setContactMsg((m) => ({ ...m, [pidKey]: "" }));
                        try {
                          const contact = await getContact(pid);
                          const ownerName = String(contact.owner_name || "").trim();
                          const advNo = String(contact.adv_number || contact.advNo || p.adv_number || p.ad_number || p.id || "").trim();
                          const sent = "Contact details sent to your registered email/SMS.";
                          const who = ownerName ? ` (${ownerName})` : "";
                          const label = advNo ? ` Ad #${advNo}${who}.` : ` Ad${who}.`;
                          setContacted((c) => ({ ...c, [pidKey]: true }));
                          setContactMsg((m) => ({ ...m, [pidKey]: `${sent}${label}`.trim() }));
                        } catch (e: any) {
                          setContactMsg((m) => ({ ...m, [pidKey]: e.message || "Locked" }));
                        }
                      }}
                    >
                      {contacted[pidKey] || p.contacted ? "Contacted" : "Contact owner"}
                    </button>
                    <span className="muted">{contactMsg[pidKey] || ""}</span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
        {!items.length ? (
          <div className="col-12 muted" style={{ marginTop: 8 }}>
            No Upload yet thanks for reaching us.
          </div>
        ) : null}
      </div>

      <button
        className="fab-arrow"
        onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
        aria-label="Scroll to top"
        title="Top"
      >
        ↑
      </button>
      </div>
    </div>
  );
}

