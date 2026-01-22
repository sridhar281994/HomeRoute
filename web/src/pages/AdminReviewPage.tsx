import { useEffect, useState } from "react";
import {
  adminApprove,
  adminImageApprove,
  adminImageReject,
  adminImagesPending,
  adminLogs,
  adminOwnerApprove,
  adminOwnerReject,
  adminOwnersPending,
  adminPending,
  adminReject,
  getSession,
  toApiUrl,
} from "../api";
import { useNavigate } from "react-router-dom";
import { sharePost } from "../share";

export default function AdminReviewPage() {
  const nav = useNavigate();
  const [items, setItems] = useState<any[]>([]);
  const [owners, setOwners] = useState<any[]>([]);
  const [images, setImages] = useState<any[]>([]);
  const [violations, setViolations] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [reasonById, setReasonById] = useState<Record<string, string>>({});

  async function load() {
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

  useEffect(() => {
    const s = getSession();
    const role = String(s.user?.role || "").toLowerCase();
    if (!s.token || role !== "admin") {
      nav("/home");
      return;
    }
    load();
  }, []);

  return (
    <div className="panel">
      <p className="h1">Admin Review Dashboard</p>
      <div className="row">
        <button className="primary" onClick={load}>
          Refresh
        </button>
        <span className="muted">{msg}</span>
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Pending Owner Registrations</div>
        <div className="muted" style={{ marginTop: 6 }}>
          Owners must be approved before they can submit listings/images.
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
                      await load();
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
                      await load();
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

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Pending Listing Images</div>
        <div className="muted" style={{ marginTop: 6 }}>
          Duplicate images are blocked by hash at upload time.
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
                      await load();
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
                      await load();
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

      <div className="card" style={{ marginTop: 12 }}>
        <div className="h2">Rejected Media Uploads (AI moderation)</div>
        <div className="muted" style={{ marginTop: 6 }}>
          These are rejected before storage; they are logged for review.
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
                    const adv = String(p.adv_number || p.ad_number || p.id || "").trim();
                    const meta = [
                      adv ? `Ad #${adv}` : "",
                      String(p.rent_sale || "").trim(),
                      String(p.property_type || "").trim(),
                      String(p.price_display || "").trim(),
                      String(p.location_display || "").trim(),
                      `status: ${String(p.status || "").trim() || "unknown"}`,
                    ]
                      .filter(Boolean)
                      .join(" • ");
                    await sharePost({ title, text: meta ? `${title}\n${meta}` : title, url });
                  }}
                  style={{ padding: "8px 10px", minWidth: 44 }}
                >
                  📤
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
                      await load();
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
                      await adminReject(p.id);
                      await load();
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

