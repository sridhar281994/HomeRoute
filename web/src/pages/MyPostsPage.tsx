import { useEffect, useMemo, useState } from "react";
import { formatPriceDisplay, getSession, ownerDeleteProperty, ownerListProperties, toApiUrl } from "../api";
import { Link, useNavigate } from "react-router-dom";
import GuestGate from "../components/GuestGate";
import { sharePost } from "../share";
import ImageViewerModal from "../components/ImageViewerModal";
import ImageWithTinyLoader from "../components/ImageWithTinyLoader";

function groupByStatus(items: any[]) {
  const out: Record<string, any[]> = {};
  for (const it of items) {
    const k = String(it.status || "unknown").toLowerCase();
    (out[k] ||= []).push(it);
  }
  return out;
}

export default function MyPostsPage() {
  const nav = useNavigate();
  const s = getSession();
  const isLocked = !s.token;
  const [items, setItems] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  const [viewerOpen, setViewerOpen] = useState<boolean>(false);
  const [viewerUrls, setViewerUrls] = useState<string[]>([]);
  const [viewerIndex, setViewerIndex] = useState<number>(0);

  async function load() {
    setMsg("");
    try {
      const r = await ownerListProperties();
      setItems(r.items || []);
    } catch (e: any) {
      setMsg(e.message || "Failed to load");
    }
  }

  useEffect(() => {
    if (!s.token) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.token]);

  const grouped = useMemo(() => groupByStatus(items), [items]);
  const order = ["pending", "approved", "rejected", "suspended", "unknown"];

  function fmtDistance(dkm: any): string {
    const n = Number(dkm);
    if (!Number.isFinite(n)) return "— km away from you";
    const pretty = n < 10 ? n.toFixed(1) : Math.round(n).toString();
    return `${pretty} km away from you`;
  }

  function openViewer(urls: string[], index: number) {
    const clean = urls.map((u) => String(u || "").trim()).filter(Boolean);
    if (!clean.length) return;
    setViewerUrls(clean);
    setViewerIndex(Math.max(0, Math.min(index, clean.length - 1)));
    setViewerOpen(true);
  }

  if (isLocked) {
    return (
      <GuestGate
        title="My Posts"
        message="Login or register to view and manage your posts."
      />
    );
  }

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          My Posts
        </p>
        <div className="spacer" />
        <button onClick={load}>Refresh</button>
        <Link to="/home">Back</Link>
      </div>
      <p className="muted" style={{ marginTop: 6 }}>
        Shows your ads across statuses (waiting/pending and approved).
      </p>
      <div className="muted">{msg}</div>

      <div className="grid" style={{ marginTop: 12 }}>
        {order.map((k) => {
          const arr = grouped[k] || [];
          if (!arr.length) return null;
          return (
            <div className="col-12" key={k}>
              <div className="card">
                <div className="row">
                  <div className="h2" style={{ textTransform: "capitalize" }}>
                    {k} ({arr.length})
                  </div>
                </div>
                <div className="grid" style={{ marginTop: 10 }}>
                  {arr.map((p) => {
                    const adNo = String(p.adv_number || p.ad_number || p.id || "").trim() || "—";
                    const districtLabel = String(p.district || "").trim() || "—";
                    const areaLabel = String(p.area || "").trim() || "—";
                    const priceLabel = formatPriceDisplay(p.price_display || p.price) || "—";
                    const distanceLabel = fmtDistance(p.distance_km);
                    const imageUrls = (Array.isArray(p.images) ? p.images : [])
                      .filter((m: any) => !String(m?.content_type || "").toLowerCase().startsWith("video/"))
                      .map((m: any) => toApiUrl(String(m?.url || "")))
                      .filter(Boolean);
                    return (
                    <div className="col-12" key={p.id}>
                      <div className="card post-card">
                        <div className="post-header">
                          <div className="post-avatar" aria-hidden="true">
                            {String(p.title || "A").trim().slice(0, 1).toUpperCase()}
                          </div>
                          <div>
                            <div className="muted post-meta">
                              Ad number: {adNo} • District: {districtLabel} • Area: {areaLabel} • Price: {priceLabel} • {distanceLabel} • status: {p.status}
                              {p.created_at ? ` • ${new Date(p.created_at).toLocaleString()}` : ""}
                            </div>
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
                                `Ad number: ${adNo}`,
                                `District: ${districtLabel}`,
                                `Area: ${areaLabel}`,
                                `Price: ${priceLabel}`,
                                distanceLabel,
                              ]
                                .filter(Boolean)
                                .join(" • ");
                              const text = [title, meta].filter(Boolean).join("\n");
                              const res = await sharePost({ title, text, url });
                              if (res === "copied") setMsg("Copied share text to clipboard.");
                            }}
                            style={{ padding: "8px 10px", minWidth: 44 }}
                          >
                            ↗️
                          </button>
                          <button
                            onClick={() => {
                              nav("/owner/add", { state: { editPost: p } });
                            }}
                          >
                            Edit
                          </button>
                          <button
                            className="danger"
                            onClick={async () => {
                              const label = String(p.adv_number || p.ad_number || p.id || "").trim();
                              const ok = window.confirm(`Delete Ad #${label}? This cannot be undone.`);
                              if (!ok) return;
                              try {
                                const pid = Number(p.id);
                                if (!Number.isInteger(pid) || pid <= 0) {
                                  setMsg("Invalid ad id.");
                                  return;
                                }
                                await ownerDeleteProperty(pid);
                                setMsg(`Deleted Ad #${label}`);
                                load();
                              } catch (e: any) {
                                setMsg(e.message || "Delete failed");
                              }
                            }}
                          >
                            Remove
                          </button>
                        </div>

                        {p.images?.length ? (
                          <div className="post-media">
                            {String(p.images[0]?.content_type || "").toLowerCase().startsWith("video/") ? (
                              <video controls preload="metadata" src={toApiUrl(p.images[0].url)} />
                            ) : (
                              <ImageWithTinyLoader
                                src={toApiUrl(p.images[0].url)}
                                alt={`Ad ${p.id} media`}
                                wrapperStyle={{ borderRadius: 14, overflow: "hidden" }}
                                imgStyle={{ width: "100%", height: 320, objectFit: "cover", cursor: "pointer" }}
                                onClick={() => {
                                  const clicked = toApiUrl(p.images[0].url);
                                  const idx = Math.max(0, imageUrls.indexOf(clicked));
                                  openViewer(imageUrls, idx);
                                }}
                              />
                            )}
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

                        {p.description ? (
                          <div className="post-body">
                            <div className="muted post-text">{p.description}</div>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  )})}
                </div>
              </div>
            </div>
          );
        })}
        {!items.length ? (
          <div className="col-12 muted" style={{ marginTop: 8 }}>
            No posts yet.
          </div>
        ) : null}
      </div>
      <ImageViewerModal open={viewerOpen} imageUrls={viewerUrls} initialIndex={viewerIndex} onClose={() => setViewerOpen(false)} />
    </div>
  );
}

