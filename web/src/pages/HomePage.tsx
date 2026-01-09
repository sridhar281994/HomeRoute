import { useEffect, useState } from "react";
import { getSession, listProperties } from "../api";
import { Link } from "react-router-dom";
import { INDIA_STATES } from "../indiaStates";
import { districtsForState } from "../indiaDistricts";

export default function HomePage() {
  const [q, setQ] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [propertyType, setPropertyType] = useState("");
  const [state, setState] = useState<string>(() => localStorage.getItem("pd_state") || "");
  const [district, setDistrict] = useState<string>(() => localStorage.getItem("pd_district") || "");
  const [items, setItems] = useState<any[]>([]);
  const [err, setErr] = useState<string>("");

  async function load() {
    setErr("");
    try {
      const isGuest = !getSession().token;
      if (isGuest && (!state || !district)) {
        setItems([]);
        throw new Error("Select State and District to search as guest.");
      }
      const res = await listProperties({
        q: q || undefined,
        max_price: maxPrice || undefined,
        rent_sale: rentSale || undefined,
        property_type: propertyType || undefined,
        state: state || undefined,
        district: district || undefined,
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
    localStorage.setItem("pd_state", state || "");
  }, [state]);

  useEffect(() => {
    localStorage.setItem("pd_district", district || "");
  }, [district]);

  const districts = districtsForState(state);

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
        <div className="col-6">
          <label className="muted">District (required for Guest)</label>
          <select value={district} onChange={(e) => setDistrict(e.target.value)} disabled={!state}>
            <option value="">{state ? "Select district…" : "Select state first"}</option>
            {districts.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
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
        <div className="col-6">
          <label className="muted">Type</label>
          <select value={propertyType} onChange={(e) => setPropertyType(e.target.value)}>
            <option value="">Any</option>
            <option value="apartment">apartment</option>
            <option value="house">house</option>
            <option value="villa">villa</option>
            <option value="studio">studio</option>
            <option value="land">land</option>
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

