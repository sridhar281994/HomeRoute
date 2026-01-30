import { useEffect, useMemo, useState } from "react";
import {
  adminApprove,
  adminDeleteProperty,
  adminImageApprove,
  adminImageReject,
  adminImagesPending,
  adminListProperties,
  adminLogs,
  adminOwnerApprove,
  adminOwnerReject,
  adminOwnersPending,
  adminPending,
  adminReject,
  adminSuspend,
  adminUpdateProperty,
  getSession,
  getCategoryCatalog,
  listLocationAreas,
  listLocationDistricts,
  listLocationStates,
  toApiUrl,
} from "../api";
import { useNavigate } from "react-router-dom";
import { sharePost } from "../share";

export default function AdminReviewPage() {
  const nav = useNavigate();
  const [items, setItems] = useState<any[]>([]);
  const [queryItems, setQueryItems] = useState<any[]>([]);
  const [owners, setOwners] = useState<any[]>([]);
  const [images, setImages] = useState<any[]>([]);
  const [violations, setViolations] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});
  const [editOpenById, setEditOpenById] = useState<Record<string, boolean>>({});
  const [editDraftById, setEditDraftById] = useState<Record<string, any>>({});

  // Filters (match HomePage shape)
  const [q, setQ] = useState<string>("");
  const [status, setStatus] = useState<string>("");
  const [need, setNeed] = useState<string>("");
  const [maxPrice, setMaxPrice] = useState("");
  const [rentSale, setRentSale] = useState("");
  const [state, setState] = useState<string>("");
  const [district, setDistrict] = useState<string>("");
  const [areas, setAreas] = useState<string[]>([]);
  const [areaSearch, setAreaSearch] = useState<string>("");
  const [sortBudget, setSortBudget] = useState<string>("");
  const [postedWithinDays, setPostedWithinDays] = useState<string>("");
  const [limit, setLimit] = useState<string>("50");
  const [catalog, setCatalog] = useState<any>(null);
  const [categoryMsg, setCategoryMsg] = useState<string>("");
  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [districtOptions, setDistrictOptions] = useState<string[]>([]);
  const [areaOptions, setAreaOptions] = useState<string[]>([]);

  async function loadQueues() {
    setMsg("");
    try {
      const [resListings, resOwners, resImages, resLogs] = await Promise.all([
        adminPending(),
        adminOwnersPending(),
        adminImagesPending(),
        adminLogs({ entity_type: "property_media_upload", limit: 200 }),
      ]);
      setItems(resListings.items || []);
      setOwners(resOwners.items || []);
      setImages(resImages.items || []);
      setViolations((resLogs.items || []).filter((x: any) => String(x.action || "").toLowerCase() === "reject"));
    } catch (e: any) {
      setMsg(e.message || "Failed");
    }
  }

  async function runQuery() {
    setMsg("");
    try {
      const maxPriceTrim = String(maxPrice || "").trim();
      const maxPriceParam = /^\d+$/.test(maxPriceTrim) ? maxPriceTrim : undefined;
      const limitTrim = String(limit || "").trim();
      const limitNum = /^\d+$/.test(limitTrim) ? Math.max(1, Math.min(200, parseInt(limitTrim, 10))) : 50;
      const res = await adminListProperties({
        q: String(q || "").trim() || undefined,
        status: String(status || "").trim() || undefined,
        property_type: String(need || "").trim() || undefined,
        max_price: maxPriceParam,
        rent_sale: rentSale || undefined,
        state: state || undefined,
        district: district || undefined,
        area: areas.length ? areas.join(",") : undefined,
        sort_budget: sortBudget || undefined,
        posted_within_days: postedWithinDays || undefined,
        limit: limitNum,
      });
      setQueryItems(res.items || []);
    } catch (e: any) {
      setMsg(e.message || "Query failed");
    }
  }

  useEffect(() => {
    const s = getSession();
    const role = String(s.user?.role || "").toLowerCase();
    if (!s.token || role !== "admin") {
      nav("/home");
      return;
    }
    loadQueues();
    runQuery();
  }, []);

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
  const categoryHint = categoryMsg || (needGroups.length ? "" : "Categories unavailable.");

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
    if (!state) {
      setDistrictOptions([]);
      setDistrict("");
      setAreaOptions([]);
      setAreas([]);
      setAreaSearch("");
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
      setAreas([]);
      setAreaSearch("");
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
        const warn = String((c as any)?.warning || "").trim();
        setCategoryMsg(warn);
      } catch {
        setCategoryMsg("Categories unavailable. Check API /meta/categories.");
      }
    })();
  }, []);

  return (
    <div className="panel">
      <p className="h1">Admin Review Dashboard</p>
      <div className="row">
        <button className="primary" onClick={loadQueues}>
          Refresh queues
        </button>
        <button onClick={runQuery}>Run query</button>
        <span className="muted">{msg}</span>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Query Ads (full control)</div>
        <div className="muted" style={{ marginTop: 6 }}>
          Admin can search, edit, approve, reject, suspend, or delete any ad.
        </div>

        <div className="grid" style={{ marginTop: 10 }}>
          <div className="col-6">
            <label className="muted">Search (title/location)</label>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" />
          </div>
          <div className="col-6">
            <label className="muted">Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Any</option>
              <option value="approved">Approved</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
              <option value="suspended">Suspended</option>
            </select>
          </div>
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
                  const qq = String(areaSearch || "").trim().toLowerCase();
                  return !qq || a.toLowerCase().includes(qq);
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
            <input value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} inputMode="numeric" />
          </div>
          <div className="col-6">
            <label className="muted">Rent/Sale</label>
            <select value={rentSale} onChange={(e) => setRentSale(e.target.value)}>
              <option value="">Any</option>
              <option value="rent">Rent</option>
              <option value="sale">Sale</option>
            </select>
          </div>
          <div className="col-6">
            <label className="muted">Limit</label>
            <input value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="numeric" />
          </div>
        </div>

        <div className="grid" style={{ marginTop: 12 }}>
          <div className="col-12">
            <div className="h2">Results</div>
          </div>
          {queryItems.map((p) => {
            const pid = Number(p.id);
            const shareUrl = Number.isInteger(pid) && pid > 0 ? `${window.location.origin}/property/${pid}` : window.location.href;
            const editKey = String(pid);
            const isOpen = !!editOpenById[editKey];
            const draft = editDraftById[editKey] || {};
            return (
              <div key={p.id} className="col-12">
                <div className="card">
                  <div className="row">
                    <div>
                      <div className="h2">
                        Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} — {p.title}
                      </div>
                      <div className="muted">
                        {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display} • status: {p.status}
                      </div>
                      {p.moderation_reason ? <div className="muted">Moderation reason: {p.moderation_reason}</div> : null}
                    </div>
                    <div className="spacer" />
                    <button
                      type="button"
                      title="Share"
                      aria-label="Share"
                      onClick={async () => {
                        const title = String(p.title || "Property").trim() || "Property";
                        const meta = [
                          String(p.rent_sale || "").trim(),
                          String(p.property_type || "").trim(),
                          String(p.price_display || "").trim(),
                          String(p.location_display || "").trim(),
                        ]
                          .filter(Boolean)
                          .join(" • ");
                        const text = [title, meta].filter(Boolean).join("\n");
                        await sharePost({ title, text, url: shareUrl });
                      }}
                      style={{ padding: "8px 10px", minWidth: 44 }}
                    >
                      ↗️
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setEditOpenById((prev) => ({ ...prev, [editKey]: !prev[editKey] }));
                        setEditDraftById((prev) => ({
                          ...prev,
                          [editKey]: prev[editKey] || {
                            title: p.title || "",
                            description: p.description || "",
                            price: p.price ?? 0,
                            rent_sale: p.rent_sale || "",
                            property_type: p.property_type || "",
                            state: p.state || "",
                            district: p.district || "",
                            area: p.area || "",
                            contact_phone: p.contact_phone || "",
                            contact_email: p.contact_email || "",
                          },
                        }));
                      }}
                    >
                      {isOpen ? "Close edit" : "Edit"}
                    </button>
                    <button
                      onClick={async () => {
                        try {
                          await adminApprove(p.id);
                          await runQuery();
                        } catch (e: any) {
                          setMsg(e.message || "Approve failed");
                        }
                      }}
                    >
                      Approve
                    </button>
                    <button
                      className="danger"
                      onClick={async () => {
                        try {
                          await adminReject(p.id, reasonById[`prop:${p.id}`] || "");
                          await runQuery();
                        } catch (e: any) {
                          setMsg(e.message || "Reject failed");
                        }
                      }}
                    >
                      Reject
                    </button>
                    <button
                      className="danger"
                      onClick={async () => {
                        try {
                          await adminSuspend(p.id, reasonById[`prop:${p.id}`] || "");
                          await runQuery();
                        } catch (e: any) {
                          setMsg(e.message || "Suspend failed");
                        }
                      }}
                    >
                      Suspend
                    </button>
                    <button
                      className="danger"
                      onClick={async () => {
                        if (!window.confirm(`Delete Ad #${String(p.adv_number || p.ad_number || p.id || "").trim()}? This cannot be undone.`)) return;
                        try {
                          await adminDeleteProperty(p.id);
                          await runQuery();
                        } catch (e: any) {
                          setMsg(e.message || "Delete failed");
                        }
                      }}
                    >
                      Delete
                    </button>
                  </div>

                  <div className="row" style={{ marginTop: 10 }}>
                    <input
                      placeholder="Reject reason (optional)"
                      value={reasonById[`prop:${p.id}`] || ""}
                      onChange={(e) => setReasonById((prev) => ({ ...prev, [`prop:${p.id}`]: e.target.value }))}
                      style={{ minWidth: 260 }}
                    />
                    <div className="spacer" />
                    {p.images?.length ? (
                      <img
                        src={toApiUrl(p.images[0].url)}
                        alt={`Listing ${p.id} preview`}
                        style={{
                          width: 180,
                          height: 120,
                          objectFit: "cover",
                          borderRadius: 12,
                          border: "1px solid rgba(255,255,255,.14)",
                          background: "rgba(0,0,0,.25)",
                        }}
                        loading="lazy"
                      />
                    ) : null}
                  </div>

                  {isOpen ? (
                    <div className="grid" style={{ marginTop: 12 }}>
                      <div className="col-6">
                        <label className="muted">Title</label>
                        <input value={draft.title || ""} onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, title: e.target.value } }))} />
                      </div>
                      <div className="col-6">
                        <label className="muted">Price</label>
                        <input
                          value={String(draft.price ?? "")}
                          inputMode="numeric"
                          onChange={(e) => {
                            const raw = String(e.target.value || "").trim();
                            const n = raw === "" ? "" : parseInt(raw, 10);
                            setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, price: Number.isFinite(n as any) ? n : "" } }));
                          }}
                        />
                      </div>
                      <div className="col-6">
                        <label className="muted">Rent/Sale</label>
                        <select value={draft.rent_sale || ""} onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, rent_sale: e.target.value } }))}>
                          <option value="rent">Rent</option>
                          <option value="sale">Sale</option>
                        </select>
                      </div>
                      <div className="col-6">
                        <label className="muted">Need category</label>
                        <input
                          value={draft.property_type || ""}
                          onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, property_type: e.target.value } }))}
                        />
                      </div>
                      <div className="col-12">
                        <label className="muted">Description</label>
                        <textarea
                          value={draft.description || ""}
                          onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, description: e.target.value } }))}
                          rows={3}
                        />
                      </div>
                      <div className="col-6">
                        <label className="muted">State</label>
                        <input value={draft.state || ""} onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, state: e.target.value } }))} />
                      </div>
                      <div className="col-6">
                        <label className="muted">District</label>
                        <input value={draft.district || ""} onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, district: e.target.value } }))} />
                      </div>
                      <div className="col-6">
                        <label className="muted">Area</label>
                        <input value={draft.area || ""} onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, area: e.target.value } }))} />
                      </div>
                      <div className="col-6">
                        <label className="muted">Contact phone</label>
                        <input
                          value={draft.contact_phone || ""}
                          onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, contact_phone: e.target.value } }))}
                        />
                      </div>
                      <div className="col-6">
                        <label className="muted">Contact email</label>
                        <input
                          value={draft.contact_email || ""}
                          onChange={(e) => setEditDraftById((prev) => ({ ...prev, [editKey]: { ...draft, contact_email: e.target.value } }))}
                        />
                      </div>
                      <div className="col-12 row">
                        <button
                          className="primary"
                          onClick={async () => {
                            try {
                              await adminUpdateProperty(pid, {
                                title: String(draft.title || "").trim() || null,
                                description: String(draft.description || "").trim(),
                                price: typeof draft.price === "number" ? draft.price : null,
                                rent_sale: String(draft.rent_sale || "").trim() || null,
                                property_type: String(draft.property_type || "").trim() || null,
                                state: String(draft.state || "").trim() || null,
                                district: String(draft.district || "").trim() || null,
                                area: String(draft.area || "").trim() || null,
                                contact_phone: String(draft.contact_phone || "").trim(),
                                contact_email: String(draft.contact_email || "").trim(),
                              });
                              setMsg("Saved.");
                              setEditOpenById((prev) => ({ ...prev, [editKey]: false }));
                              await runQuery();
                            } catch (e: any) {
                              setMsg(e.message || "Save failed");
                            }
                          }}
                        >
                          Save changes
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              </div>
            );
          })}
          {!queryItems.length ? <div className="col-12 muted">No results.</div> : null}
        </div>
      </div>

      <div className="card admin-queue admin-queue--owners" style={{ marginTop: 12 }}>
        <div className="row admin-queue-head">
          <div>
            <div className="h2">Pending Owner Registrations</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Owners must be approved before they can submit listings/images.
            </div>
          </div>
          <div className="spacer" />
          <span className="admin-pill">{owners.length}</span>
        </div>
        <div className="grid" style={{ marginTop: 10 }}>
          {owners.map((o) => (
            <div key={o.id} className="col-12">
              <div className="row">
                <div>
                  <div className="h2">
                    #{o.id} — {o.company_name || o.name || o.username}
                  </div>
                  <div className="muted">
                    {o.owner_category || "owner"} • {o.state} / {o.district} • {o.phone || "no phone"} • {o.email}
                  </div>
                  {o.company_address ? <div className="muted">Address: {o.company_address}</div> : null}
                </div>
                <div className="spacer" />
                <input
                  placeholder="Reject reason (optional)"
                  value={reasonById[`owner:${o.id}`] || ""}
                  onChange={(e) => setReasonById((prev) => ({ ...prev, [`owner:${o.id}`]: e.target.value }))}
                  style={{ minWidth: 260 }}
                />
                <button
                  onClick={async () => {
                    try {
                      await adminOwnerApprove(o.id);
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Approve failed");
                    }
                  }}
                >
                  Approve
                </button>
                <button
                  className="danger"
                  onClick={async () => {
                    try {
                      await adminOwnerReject(o.id, reasonById[`owner:${o.id}`] || "");
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Reject failed");
                    }
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
          {!owners.length ? <div className="col-12 muted">No pending owners.</div> : null}
        </div>
      </div>

      <div className="card admin-queue admin-queue--images" style={{ marginTop: 12 }}>
        <div className="row admin-queue-head">
          <div>
            <div className="h2">Pending Listing Images</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Duplicate images are blocked by hash at upload time.
            </div>
          </div>
          <div className="spacer" />
          <span className="admin-pill">{images.length}</span>
        </div>
        <div className="grid" style={{ marginTop: 10 }}>
          {images.map((img) => (
            <div key={img.id} className="col-12">
              <div className="row">
                <div>
                  <div className="h2">
                    Image #{img.id} — Listing #{img.property_id} {img.property_title ? `(${img.property_title})` : ""}
                  </div>
                  <div className="muted">
                    hash: {img.image_hash?.slice(0, 12)}… • {img.content_type} • {img.size_bytes} bytes
                  </div>
                  <div className="muted">
                    Preview:{" "}
                    <a href={toApiUrl(img.url)} target="_blank" rel="noreferrer">
                      {img.url}
                    </a>
                  </div>
                </div>
                <div className="spacer" />
                {img.url ? (
                  <img
                    src={toApiUrl(img.url)}
                    alt={`Listing ${img.property_id} image ${img.id}`}
                    style={{
                      width: 180,
                      height: 120,
                      objectFit: "cover",
                      borderRadius: 12,
                      border: "1px solid rgba(255,255,255,.14)",
                      background: "rgba(0,0,0,.25)",
                    }}
                    loading="lazy"
                  />
                ) : null}
                <div className="spacer" />
                <input
                  placeholder="Reject reason (optional)"
                  value={reasonById[`img:${img.id}`] || ""}
                  onChange={(e) => setReasonById((prev) => ({ ...prev, [`img:${img.id}`]: e.target.value }))}
                  style={{ minWidth: 260 }}
                />
                <button
                  onClick={async () => {
                    try {
                      await adminImageApprove(img.id);
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Approve failed");
                    }
                  }}
                >
                  Approve
                </button>
                <button
                  className="danger"
                  onClick={async () => {
                    try {
                      await adminImageReject(img.id, reasonById[`img:${img.id}`] || "");
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Reject failed");
                    }
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
          {!images.length ? <div className="col-12 muted">No pending images.</div> : null}
        </div>
      </div>

      <div className="card admin-queue admin-queue--ai" style={{ marginTop: 12 }}>
        <div className="row admin-queue-head">
          <div>
            <div className="h2">Rejected Media Uploads (AI moderation)</div>
            <div className="muted" style={{ marginTop: 6 }}>
              These are rejected before storage; they are logged for review.
            </div>
          </div>
          <div className="spacer" />
          <span className="admin-pill">{violations.length}</span>
        </div>
        <div className="grid" style={{ marginTop: 10 }}>
          {violations.map((v) => (
            <div key={v.id} className="col-12">
              <div className="row">
                <div>
                  <div className="h2">Log #{v.id} — Property #{v.entity_id}</div>
                  <div className="muted">
                    actor: {v.actor_user_id} • action: {v.action} • {v.created_at ? new Date(v.created_at).toLocaleString() : ""}
                  </div>
                  <div className="muted" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                    {v.reason}
                  </div>
                </div>
              </div>
            </div>
          ))}
          {!violations.length ? <div className="col-12 muted">No AI moderation rejections logged.</div> : null}
        </div>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="h2">Pending Listings</div>
        </div>
        {items.map((p) => (
          <div key={p.id} className="col-12">
            <div className="card">
              <div className="row">
                <div>
                  <div className="h2">
                    Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} — {p.title}
                  </div>
                  <div className="muted">
                    {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display} • status: {p.status}
                  </div>
                  {p.description ? (
                    <div className="muted" style={{ marginTop: 6, whiteSpace: "pre-wrap" }}>
                      {p.description}
                    </div>
                  ) : null}
                  <div className="muted" style={{ marginTop: 6 }}>
                    Owner: {p.owner_company_name || p.owner_name || p.owner_username || "—"}
                    {p.owner_id ? ` (id: ${p.owner_id})` : ""}
                    {p.owner_phone ? ` • owner phone: ${p.owner_phone}` : ""}
                    {p.owner_email ? ` • owner email: ${p.owner_email}` : ""}
                  </div>
                  {p.contact_phone || p.contact_email ? (
                    <div className="muted">
                      Ad contact: {p.contact_phone || "—"} {p.contact_email ? ` • ${p.contact_email}` : ""}
                    </div>
                  ) : null}
                  {p.address ? <div className="muted">Address: {p.address}</div> : null}
                  {p.moderation_reason ? (
                    <div className="muted" style={{ marginTop: 6 }}>
                      Moderation reason: {p.moderation_reason}
                    </div>
                  ) : null}
                </div>
                <div className="spacer" />
                <button
                  type="button"
                  title="Share"
                  aria-label="Share"
                  onClick={async () => {
                    const pid = Number(p.id);
                    const url = Number.isInteger(pid) && pid > 0 ? `${window.location.origin}/property/${pid}` : window.location.href;
                    const title = String(p.title || "Property").trim() || "Property";
                    const meta = [
                      String(p.rent_sale || "").trim(),
                      String(p.property_type || "").trim(),
                      String(p.price_display || "").trim(),
                      String(p.location_display || "").trim(),
                    ]
                      .filter(Boolean)
                      .join(" • ");
                  const text = [title, meta].filter(Boolean).join("\n");
                  await sharePost({ title, text, url });
                  }}
                  style={{ padding: "8px 10px", minWidth: 44 }}
                >
                  ↗️
                </button>
                {p.images?.length ? (
                  String(p.images[0]?.content_type || "").toLowerCase().startsWith("video/") ? (
                    <video
                      controls
                      preload="metadata"
                      src={toApiUrl(p.images[0].url)}
                      style={{
                        width: 180,
                        height: 120,
                        objectFit: "cover",
                        borderRadius: 12,
                        border: "1px solid rgba(255,255,255,.14)",
                        background: "rgba(0,0,0,.25)",
                      }}
                    />
                  ) : (
                    <img
                      src={toApiUrl(p.images[0].url)}
                      alt={`Listing ${p.id} preview`}
                      style={{
                        width: 180,
                        height: 120,
                        objectFit: "cover",
                        borderRadius: 12,
                        border: "1px solid rgba(255,255,255,.14)",
                        background: "rgba(0,0,0,.25)",
                      }}
                      loading="lazy"
                    />
                  )
                ) : null}
                <button
                  onClick={async () => {
                    try {
                      await adminApprove(p.id);
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Approve failed");
                    }
                  }}
                >
                  Approve
                </button>
                <button
                  className="danger"
                  onClick={async () => {
                    try {
                      await adminReject(p.id, reasonById[`prop:${p.id}`] || "");
                      await loadQueues();
                    } catch (e: any) {
                      setMsg(e.message || "Reject failed");
                    }
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
          </div>
        ))}
        {!items.length ? (
          <div className="col-12 muted" style={{ marginTop: 8 }}>
            No pending listings.
          </div>
        ) : null}
      </div>
    </div>
  );
}

