import { useEffect, useMemo, useState } from "react";
import { getCategoryCatalog, listNearbyProperties, listProperties, toApiUrl } from "../api";
import { Link } from "react-router-dom";
import { getAreas, getDistricts, getStatesForDistrict, getBrowserGps, isValidAreaSelection } from "../location";

export default function HomePage() {
  const [need, setNeed] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [district, setDistrict] = useState<string>(() => localStorage.getItem("pd_district") || "");
  const [state, setState] = useState<string>(() => localStorage.getItem("pd_state") || "");
  const [area, setArea] = useState<string>(() => localStorage.getItem("pd_area") || "");
  const [radiusKm, setRadiusKm] = useState<string>(() => localStorage.getItem("pd_radius_km") || "20");
  const [sortBudget, setSortBudget] = useState<string>("top");
  const [postedWithinDays, setPostedWithinDays] = useState<string>("");
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string>("");
  const [gps, setGps] = useState<{ lat: number; lon: number } | null>(null);
  const [catalog, setCatalog] = useState<any>(null);

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
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
        setErr(e?.message || "Unable to access GPS.");
      }
    })();
  }, []);

  const districts = useMemo(() => getDistricts(), []);
  const states = useMemo(() => (district ? getStatesForDistrict(district) : []), [district]);
  const areas = useMemo(() => (district && state ? getAreas(district, state) : []), [district, state]);

  return (
    <div className="page-home">
      <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Home  🏡✨  <span className="muted">Discover amazing places</span>
        </p>
        <div className="spacer" />
        <button onClick={load}>Refresh</button>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">District (optional)</label>
          <select
            value={district}
            onChange={(e) => {
              setDistrict(e.target.value);
              setState("");
              setArea("");
            }}
          >
            <option value="">Select district…</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">State (optional)</label>
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setArea("");
            }}
            disabled={!district}
          >
            <option value="">{district ? "Select state…" : "Select district first"}</option>
            {states.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Area (optional)</label>
          <select value={area} onChange={(e) => setArea(e.target.value)} disabled={!district || !state}>
            <option value="">{district && state ? "Select area…" : "Select district + state first"}</option>
            {areas.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          {area && !isValidAreaSelection(district, state, area) ? (
            <div className="muted" style={{ marginTop: 6 }}>
              Invalid area selection.
            </div>
          ) : null}
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
            <option value="rent">rent</option>
            <option value="sale">sale</option>
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
                    Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} • {p.rent_sale} • {p.property_type} • {p.price_display} •{" "}
                    {p.location_display}
                    {p.created_at ? ` • ${new Date(p.created_at).toLocaleDateString()}` : ""}
                  </div>
                </div>
                <div className="spacer" />
                <Link to={`/property/${p.id}`}>Open ➜</Link>
              </div>

              {p.images?.length ? (
                <div className="post-media">
                  {String(p.images[0]?.content_type || "").toLowerCase().startsWith("video/") ? (
                    <video controls preload="metadata" src={toApiUrl(p.images[0].url)} />
                  ) : (
                    <img src={toApiUrl(p.images[0].url)} alt={`Ad ${p.id} media`} loading="lazy" />
                  )}
                </div>
              ) : null}

              {p.description ? (
                <div className="post-body">
                  <div className="muted post-text">
                    {String(p.description).length > 220 ? `${String(p.description).slice(0, 220)}…` : p.description}
                  </div>
                </div>
              ) : null}
            </div>
          </div>
        ))}
        {!items.length ? (
          <div className="col-12 muted" style={{ marginTop: 8 }}>
            No properties yet (demo data will seed on first run).
          </div>
        ) : null}
      </div>
      </div>
    </div>
  );
}

