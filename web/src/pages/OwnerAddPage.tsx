import { useEffect, useState } from "react";
import { getSession, ownerCreateProperty, ownerDeleteProperty, ownerListProperties, uploadPropertyImage } from "../api";
import { Link, useNavigate } from "react-router-dom";
import { INDIA_STATES } from "../indiaStates";
import { districtsForState } from "../indiaDistricts";

export default function OwnerAddPage() {
  const nav = useNavigate();
  const s = getSession();
  const [title, setTitle] = useState("");
  const [state, setState] = useState<string>(s.user?.state || localStorage.getItem("pd_state") || "");
  const [district, setDistrict] = useState<string>(s.user?.district || localStorage.getItem("pd_district") || "");
  const [price, setPrice] = useState("");
  const [rentSale, setRentSale] = useState("rent");
  const [category, setCategory] = useState<"materials" | "services" | "property">("property");
  const [contactPhone, setContactPhone] = useState("");
  const [useCompanyName, setUseCompanyName] = useState<boolean>(false);
  const [companyName, setCompanyName] = useState<string>(((s.user as any)?.company_name as string) || "");
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [myAds, setMyAds] = useState<any[]>([]);
  const [myAdsMsg, setMyAdsMsg] = useState<string>("");

  useEffect(() => {
    if (!s.token) nav("/login");
  }, [nav, s.token]);

  useEffect(() => {
    // Default to "Yes" if company name already exists.
    const existing = (((getSession().user as any)?.company_name as string) || "").trim();
    if (existing) setUseCompanyName(true);
  }, []);

  useEffect(() => {
    localStorage.setItem("pd_state", state || "");
  }, [state]);
  useEffect(() => {
    localStorage.setItem("pd_district", district || "");
  }, [district]);

  if ((s.user?.role || "").toLowerCase() !== "owner") {
    return (
      <div className="panel">
        <p className="h1">Publish Ad  🏢</p>
        <p className="muted">Owner access only. Please login/register with an Owner account to publish ads.</p>
        <Link to="/home">Back</Link>
      </div>
    );
  }

  const districts = districtsForState(state);

  async function loadMyAds() {
    setMyAdsMsg("");
    try {
      const r = await ownerListProperties();
      setMyAds(r.items || []);
    } catch (e: any) {
      setMyAdsMsg(e.message || "Failed to load your ads");
    }
  }

  useEffect(() => {
    loadMyAds();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Publish Ad  ➕
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">
        Create the ad first, then upload photos.
      </p>
      <p className="muted" style={{ marginTop: 6 }}>
        Important note: only the owner who created an ad can remove it.
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">State</label>
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
          <label className="muted">District</label>
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
          <label className="muted">Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Category (materials / services / property)</label>
          <select value={category} onChange={(e) => setCategory(e.target.value as any)}>
            <option value="materials">materials</option>
            <option value="services">services</option>
            <option value="property">property</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Publish with company name?</label>
          <select value={useCompanyName ? "yes" : "no"} onChange={(e) => setUseCompanyName(e.target.value === "yes")}>
            <option value="no">No</option>
            <option value="yes">Yes</option>
          </select>
        </div>
        {useCompanyName ? (
          <div className="col-12">
            <label className="muted">Company name</label>
            <input value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Enter company name" />
          </div>
        ) : null}
        <div className="col-6">
          <label className="muted">Price</label>
          <input value={price} onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Rent/Sale</label>
          <select value={rentSale} onChange={(e) => setRentSale(e.target.value)}>
            <option value="rent">rent</option>
            <option value="sale">sale</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Contact phone</label>
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
        </div>

        <div className="col-12 row">
          <button
            className="primary"
            onClick={async () => {
              setMsg("");
              try {
                if (useCompanyName && !companyName.trim()) throw new Error("Please enter company name (or select No).");
                const res = await ownerCreateProperty({
                  state,
                  district,
                  title,
                  // UI request: remove explicit Location/Address.
                  // Use district as a simple display + duplicate detection key.
                  location: district || "",
                  address: "",
                  price: Number(price || 0),
                  rent_sale: rentSale,
                  property_type: category,
                  contact_phone: contactPhone,
                  contact_email: "",
                  company_name: useCompanyName ? companyName.trim() : "",
                  amenities: [],
                });
                setPropertyId(res.id);
                setMsg(`Created listing #${res.id} (status: ${res.status}). Upload photos below.`);
                loadMyAds();
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Submit listing (goes to admin review)
          </button>
          <span className="muted">{msg}</span>
        </div>

        <div className="col-12">
          <div className="card">
            <div className="h2">Upload photos</div>
            <p className="muted" style={{ marginTop: 6 }}>
              Supports multiple images. Stored on server under <code>/uploads</code>.
            </p>
            <input
              type="file"
              multiple
              accept="image/*"
              onChange={(e) => setFiles(e.target.files)}
            />
            <div className="row" style={{ marginTop: 10 }}>
              <button
                onClick={async () => {
                  if (!propertyId) return setMsg("Create the listing first.");
                  if (!files?.length) return setMsg("Choose at least one image.");
                  try {
                    for (let i = 0; i < files.length; i++) {
                      await uploadPropertyImage(propertyId, files[i], i);
                    }
                    setMsg(`Uploaded ${files.length} image(s) to listing #${propertyId}.`);
                  } catch (e: any) {
                    setMsg(e.message || "Upload failed");
                  }
                }}
              >
                Upload
              </button>
              <span className="muted">
                {propertyId ? `Listing: #${propertyId}` : "Listing: (not created yet)"}
              </span>
            </div>
          </div>
        </div>

        <div className="col-12">
          <div className="card">
            <div className="row">
              <div className="h2">My Ads</div>
              <div className="spacer" />
              <button onClick={loadMyAds}>Refresh</button>
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              {myAdsMsg}
            </div>
            <div className="grid" style={{ marginTop: 10 }}>
              {myAds.map((p) => (
                <div className="col-12" key={p.id}>
                  <div className="card">
                    <div className="row">
                      <div>
                        <div className="h2">
                          #{p.id} • {p.title}
                        </div>
                        <div className="muted">
                          Status: {p.status} {p.created_at ? `• ${new Date(p.created_at).toLocaleString()}` : ""}
                        </div>
                      </div>
                      <div className="spacer" />
                      <button
                        className="danger"
                        onClick={async () => {
                          const ok = window.confirm(`Delete Ad #${p.id}? This cannot be undone.`);
                          if (!ok) return;
                          try {
                            await ownerDeleteProperty(Number(p.id));
                            setMsg(`Deleted Ad #${p.id}`);
                            loadMyAds();
                          } catch (e: any) {
                            setMsg(e.message || "Delete failed");
                          }
                        }}
                      >
                        Remove post
                      </button>
                    </div>
                  </div>
                </div>
              ))}
              {!myAds.length ? (
                <div className="col-12 muted">No ads yet.</div>
              ) : null}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

