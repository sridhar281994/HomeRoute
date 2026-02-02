import { useEffect, useMemo, useState } from "react";
import {
  getCategoryCatalog,
  getMe,
  getSession,
  listLocationAreas,
  listLocationDistricts,
  listLocationStates,
  ownerCreateProperty,
  ownerDeleteProperty,
  ownerListProperties,
  ownerPublishProperty,
  uploadPropertyImage,
} from "../api";
import { Link } from "react-router-dom";
import { getBrowserGps } from "../location";
import { requestBrowserMediaAccess } from "../permissions";
import GuestGate from "../components/GuestGate";

export default function OwnerAddPage() {
  const s = getSession();
  const isLocked = !s.token;
  const [postGroup, setPostGroup] = useState<"property_material" | "services">("property_material");
  const [title, setTitle] = useState("");
  const [state, setState] = useState<string>(((s.user as any)?.state as string) || localStorage.getItem("pd_state") || "");
  const [district, setDistrict] = useState<string>(((s.user as any)?.district as string) || localStorage.getItem("pd_district") || "");
  const [area, setArea] = useState<string>(localStorage.getItem("pd_area") || "");
  const [price, setPrice] = useState("");
  const [rentSale, setRentSale] = useState("rent");
  const [propertyType, setPropertyType] = useState<string>("");
  const [contactPhone, setContactPhone] = useState("");
  const [useCompanyName, setUseCompanyName] = useState<boolean>(false);
  const [companyName, setCompanyName] = useState<string>(((s.user as any)?.company_name as string) || "");
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [adNumber, setAdNumber] = useState<string>("");
  const [msg, setMsg] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);
  const [selectedMediaSummary, setSelectedMediaSummary] = useState<string>("");
  const [mediaMsg, setMediaMsg] = useState<string>("");
  const [uploadStatus, setUploadStatus] = useState<string>("");
  const [myAds, setMyAds] = useState<any[]>([]);
  const [myAdsMsg, setMyAdsMsg] = useState<string>("");
  const [catalog, setCatalog] = useState<any>(null);
  const [categoryMsg, setCategoryMsg] = useState<string>("");

  function validateSelectedMedia(list: FileList | null): { ok: boolean; message: string; images: File[]; videos: File[] } {
    const arr = list ? Array.from(list) : [];
    const images = arr.filter((f) => String(f.type || "").toLowerCase().startsWith("image/"));
    const videos = arr.filter((f) => String(f.type || "").toLowerCase().startsWith("video/"));
    const others = arr.filter((f) => !String(f.type || "").toLowerCase().startsWith("image/") && !String(f.type || "").toLowerCase().startsWith("video/"));
    if (others.length) return { ok: false, message: "Only image/video files are allowed.", images: [], videos: [] };
    if (images.length > 10) return { ok: false, message: "Maximum 10 images are allowed.", images: [], videos: [] };
    if (videos.length > 1) return { ok: false, message: "Maximum 1 video is allowed.", images: [], videos: [] };
    return { ok: true, message: "", images, videos };
  }

  async function requestMediaAccess() {
    setMediaMsg("");
    try {
      await requestBrowserMediaAccess({ video: true, audio: false });
      setMediaMsg("Media access granted.");
    } catch (e: any) {
      setMediaMsg(e?.message || "Media access denied.");
    }
  }

  useEffect(() => {
    // Default to "Yes" if company name already exists.
    const existing = (((getSession().user as any)?.company_name as string) || "").trim();
    if (existing) setUseCompanyName(true);
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const c = await getCategoryCatalog();
        setCatalog(c);
        const warn = String((c as any)?.warning || "").trim();
        setCategoryMsg(warn);
        // Default to a sensible property category if user hasn't chosen one.
        if (!propertyType) {
          const all: string[] = [];
          for (const g of (c?.categories || []) as Array<{ items: string[] }>) {
            for (const it of g.items || []) {
              const label = String(it || "").trim();
              if (label) all.push(label);
            }
          }
          const pick = all.find((x) => x.toLowerCase().includes("apartment")) || all[0] || "";
          if (pick) setPropertyType(pick);
        }
      } catch {
        setCategoryMsg("Categories unavailable. Check API /meta/categories.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [districtOptions, setDistrictOptions] = useState<string[]>([]);
  const [areaOptions, setAreaOptions] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const r = await listLocationStates();
        setStateOptions((r.items || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        setStateOptions([]);
      }
    })();
  }, []);

  useEffect(() => {
    // Ensure we have the latest profile state/district (first time only).
    (async () => {
      try {
        if (!s.token) return;
        if ((state || "").trim() && (district || "").trim()) return;
        const me = await getMe();
        const u: any = me.user || {};
        if (!state && (u.state || "").trim()) setState(String(u.state || "").trim());
        if (!district && (u.district || "").trim()) setDistrict(String(u.district || "").trim());
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
    if (!s.token) return;
    loadMyAds();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.token]);

  const needGroups = (() => {
    const cats = (catalog?.categories || []) as Array<{ group: string; items: string[] }>;
    const grouped = cats
      .map((g) => ({ group: String(g.group || "").trim(), items: (g.items || []).map((x) => String(x || "").trim()).filter(Boolean) }))
      .filter((g) => g.group && g.items.length);
    return grouped;
  })();
  const needGroupsFiltered = useMemo(() => {
    const propertyGroups = new Set(["property & space", "room & stay", "construction materials"]);
    return needGroups.filter((g) => {
      const gl = String(g.group || "").trim().toLowerCase();
      const isPropertyMaterial = propertyGroups.has(gl);
      return postGroup === "property_material" ? isPropertyMaterial : !isPropertyMaterial;
    });
  }, [needGroups, postGroup]);
  const needOptionsFlat = useMemo(() => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const g of needGroupsFiltered) {
      for (const it of g.items) {
        const v = String(it || "").trim();
        const k = v.toLowerCase();
        if (!v || seen.has(k)) continue;
        seen.add(k);
        out.push(v);
      }
    }
    return out.sort((a, b) => a.localeCompare(b));
  }, [needGroupsFiltered]);

  if (isLocked) {
    return (
      <GuestGate
        title="Publish Ad"
        message="Login or register to publish ads and upload media."
      />
    );
  }

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
        Choose photos (optional), then submit.
      </p>
      <p className="muted" style={{ marginTop: 6 }}>
        Important note: only the account that created an ad can remove it.
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">State *</label>
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setDistrict("");
              setArea("");
            }}
          >
            <option value="">Select state…</option>
            {stateOptions.map((st) => (
              <option key={st} value={st}>
                {st}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">District *</label>
          <select
            value={district}
            onChange={(e) => {
              setDistrict(e.target.value);
              setArea("");
            }}
            disabled={!state}
          >
            <option value="">{state ? "Select district…" : "Select state first"}</option>
            {districtOptions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Area *</label>
          <select value={area} onChange={(e) => setArea(e.target.value)} disabled={!state || !district}>
            <option value="">{state && district ? "Select area…" : "Select state + district first"}</option>
            {areaOptions.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          {area && areaOptions.length && !areaOptions.includes(area) ? <div className="muted" style={{ marginTop: 6 }}>Invalid area selection.</div> : null}
        </div>
        <div className="col-6">
          <label className="muted">Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Publish as</label>
          <select
            value={postGroup}
            onChange={(e) => {
              const v = e.target.value === "services" ? "services" : "property_material";
              setPostGroup(v);
              // Reset category if it doesn't fit the new group.
              setPropertyType((prev) => {
                const ok = needOptionsFlat.includes(prev);
                return ok ? prev : "";
              });
            }}
          >
            <option value="property_material">Owner(property/Material)</option>
            <option value="services">Owner(services Only)</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Need category (materials / services / property)</label>
          <input
            value={propertyType}
            onChange={(e) => setPropertyType(e.target.value)}
            placeholder={needGroups.length ? "Select / type to search…" : "Loading…"}
            list="need-category-list-owner-add"
          />
          <datalist id="need-category-list-owner-add">
            {needOptionsFlat.map((it) => (
              <option key={it} value={it} />
            ))}
          </datalist>
          {categoryMsg ? <div className="muted" style={{ marginTop: 6 }}>{categoryMsg}</div> : null}
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
            <option value="rent">Rent</option>
            <option value="sale">Sale</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Contact phone</label>
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
        </div>

        <div className="col-12">
          <div className="card">
            <div className="h2">Upload media</div>
            <input
              type="file"
              multiple
              accept="image/*,video/*"
              onChange={(e) => {
                const next = e.target.files;
                const v = validateSelectedMedia(next);
                if (!v.ok) {
                  setFiles(null);
                  setSelectedMediaSummary("");
                  setMsg(v.message);
                  return;
                }
                setFiles(next);
                const parts: string[] = [];
                if (v.images.length) parts.push(`${v.images.length} image(s)`);
                if (v.videos.length) parts.push(`${v.videos.length} video`);
                setSelectedMediaSummary(parts.length ? `Selected: ${parts.join(" + ")}` : "");
              }}
            />
            {selectedMediaSummary ? <div className="muted" style={{ marginTop: 8 }}>{selectedMediaSummary}</div> : null}
            <div className="row" style={{ marginTop: 8, alignItems: "center" }}>
              <button type="button" onClick={requestMediaAccess}>
                Enable camera/media
              </button>
              <span className="muted">{mediaMsg}</span>
            </div>
            <div className="row" style={{ marginTop: 10 }}>
              <button
                onClick={async () => {
                  if (!propertyId) return setMsg("Create the listing first.");
                  if (!files?.length) return setMsg("Choose at least one image.");
                  const v = validateSelectedMedia(files);
                  if (!v.ok) return setMsg(v.message);
                  try {
                    setUploadStatus("Uploading…");
                    const ordered = [...v.images, ...v.videos];
                    for (let i = 0; i < ordered.length; i++) {
                      await uploadPropertyImage(propertyId, ordered[i], i);
                    }
                    const label = adNumber ? `Ad #${adNumber}` : `listing #${propertyId}`;
                    setMsg(`Uploaded ${ordered.length} file(s) to ${label}.`);
                    setUploadStatus("Uploaded");
                  } catch (e: any) {
                    setMsg(e.message || "Upload failed");
                    setUploadStatus("");
                  }
                }}
              >
                Upload
              </button>
              <span className="muted">
                {uploadStatus ? uploadStatus : propertyId ? `Ad: #${adNumber || propertyId}` : ""}
              </span>
            </div>
          </div>
        </div>

        <div className="col-12 row">
          <button
            className="primary"
            onClick={async () => {
              setMsg("");
              try {
                if (!state) throw new Error("Select state.");
                if (!district) throw new Error("Select district.");
                if (!area) throw new Error("Select area.");
                if (areaOptions.length && !areaOptions.includes(area)) throw new Error("Invalid area selection.");
                if (!title.trim()) throw new Error("Enter title.");
                if (!propertyType.trim()) throw new Error("Select need category.");
                if (useCompanyName && !companyName.trim()) throw new Error("Please enter company name (or select No).");

                // GPS is optional (State/District/Area are mandatory).
                // Best-effort: if user blocks location, proceed without GPS.
                let gps: { lat: number; lon: number } | null = null;
                try {
                  gps = await getBrowserGps({ timeoutMs: 8000 });
                } catch {
                  gps = null;
                }
                const payloadObj = {
                  district,
                  state,
                  area,
                  title,
                  // UI request: remove explicit Location/Address.
                  // Use district as a simple display + duplicate detection key.
                  location: area || "",
                  address: "",
                  price: Number(price || 0),
                  rent_sale: rentSale,
                  property_type: propertyType.trim(),
                  contact_phone: contactPhone,
                  contact_email: "",
                  company_name: useCompanyName ? companyName.trim() : "",
                  amenities: [],
                  gps_lat: gps ? gps.lat : null,
                  gps_lng: gps ? gps.lon : null,
                };

                // If files are selected, publish atomically (create + upload in one request).
                // This avoids leaving orphan posts when an upload fails.
                if (files?.length) {
                  const v = validateSelectedMedia(files);
                  if (!v.ok) throw new Error(v.message);
                  const ordered = [...v.images, ...v.videos];
                  const published = await ownerPublishProperty(payloadObj, ordered);
                  setPropertyId(Number(published.id));
                  setAdNumber(String(published.ad_number || published.adv_number || published.id || "").trim());
                  const label = String(published.ad_number || published.id || "").trim();
                  setMsg(`Submitted Ad #${label} (status: ${published.status}) and uploaded ${ordered.length} file(s).`);
                } else {
                  const res = await ownerCreateProperty(payloadObj);
                  setPropertyId(res.id);
                  setAdNumber(String((res as any).ad_number || (res as any).adv_number || res.id || "").trim());
                  const label = String((res as any).ad_number || res.id || "").trim();
                  setMsg(`Submitted Ad #${label} (status: ${res.status}).`);
                }
                loadMyAds();
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Submit Ad
          </button>
          <span className="muted">{msg}</span>
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
                          Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} • {p.title}
                        </div>
                        <div className="muted">
                          Status: {p.status} {p.created_at ? `• ${new Date(p.created_at).toLocaleString()}` : ""}
                        </div>
                      </div>
                      <div className="spacer" />
                      <button
                        className="danger"
                        onClick={async () => {
                          const label = String(p.adv_number || p.ad_number || p.id || "").trim();
                          const ok = window.confirm(`Delete Ad #${label}? This cannot be undone.`);
                          if (!ok) return;
                          try {
                            await ownerDeleteProperty(Number(p.id));
                            setMsg(`Deleted Ad #${label}`);
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

