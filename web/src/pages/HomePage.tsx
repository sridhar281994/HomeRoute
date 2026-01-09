import { useEffect, useMemo, useState } from "react";
import { getCategoryCatalog, getSession, listProperties } from "../api";
import { Link } from "react-router-dom";
import { INDIA_STATES } from "../indiaStates";
import { districtsForState } from "../indiaDistricts";

export default function HomePage() {
  const session = getSession();
  const [q, setQ] = useState("");
  const [need, setNeed] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [state, setState] = useState<string>(() => localStorage.getItem("pd_state") || "");
  const [district, setDistrict] = useState<string>(() => localStorage.getItem("pd_district") || "");
  const [sortBudget, setSortBudget] = useState<string>("top");
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string>("");
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
      const isGuest = !session.token;
      if (isGuest && (!state || !district)) {
        setItems([]);
        throw new Error("Select State and District to search as guest.");
      }
      const qCombined = [need, q].map((x) => (x || "").trim()).filter(Boolean).join(" ");
      const res = await listProperties({
        q: qCombined || undefined,
        max_price: maxPrice || undefined,
        rent_sale: rentSale || undefined,
        property_type: propertyType || undefined,
        // For registered users: state is auto-picked from profile by backend if omitted.
        state: isGuest ? state || undefined : undefined,
        district: district || undefined,
        sort_budget: sortBudget || undefined,
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
    // Auto-pull registered user's state into the Location filter.
    const userState = (session.user as any)?.state || "";
    if (session.token && userState) {
      setState(userState);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.token]);

  const isGuest = !session.token;
  const effectiveState = isGuest ? state : state || ((session.user as any)?.state || "");
  const districts = districtsForState(effectiveState);

  return (
    <div className="page-home">
      <div className="home-bg" aria-hidden="true" />
      <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Home  🏡✨  <span className="muted">Discover amazing places</span>
        </p>
        <div className="spacer" />
        <button onClick={load}>Refresh</button>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        {isGuest ? (
          <div className="col-6">
            <label className="muted">State (required for Guest)</label>
            <select
              value={state}
              onChange={(e) => {
                setState(e.target.value);
                setDistrict("");
              }}
            >
              <option value="">Select state…</option>
              {INDIA_STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="col-6">
            <label className="muted">State (auto from your registration)</label>
            <input value={effectiveState || ""} disabled />
          </div>
        )}
        <div className="col-6">
          <label className="muted">District {isGuest ? "(required for Guest)" : ""}</label>
          <select value={district} onChange={(e) => setDistrict(e.target.value)} disabled={!state}>
            <option value="">{effectiveState ? "Select district…" : "Select state first"}</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Building / Home Category</label>
          <select value={propertyType} onChange={(e) => setPropertyType(e.target.value)}>
            <option value="">Any</option>
            <option value="apartment">apartment</option>
            <option value="house">house</option>
            <option value="villa">villa</option>
            <option value="studio">studio</option>
            <option value="land">land</option>
          </select>
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
          <label className="muted">Sort (by budget)</label>
          <select value={sortBudget} onChange={(e) => setSortBudget(e.target.value)}>
            <option value="top">Top (high to low)</option>
            <option value="bottom">Bottom (low to high)</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Search</label>
          <input value={q} onChange={(e) => setQ(e.target.value)} />
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
          <div className="col-6" key={p.id}>
            <div className="card">
              <div className="row">
                <div>
                  <div className="h2">{p.title}</div>
                  <div className="muted">
                    {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display}
                  </div>
                </div>
                <div className="spacer" />
                <Link to={`/property/${p.id}`}>Open ➜</Link>
              </div>
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

