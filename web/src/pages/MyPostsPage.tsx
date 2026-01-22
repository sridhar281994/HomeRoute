import { useEffect, useMemo, useState } from "react";
import { getSession, ownerDeleteProperty, ownerListProperties, toApiUrl } from "../api";
import { Link } from "react-router-dom";
import GuestGate from "../components/GuestGate";
import { sharePost } from "../share";

function groupByStatus(items: any[]) {
  const out: Record<string, any[]> = {};
  for (const it of items) {
    const k = String(it.status || "unknown").toLowerCase();
    (out[k] ||= []).push(it);
  }
  return out;
}

export default function MyPostsPage() {
  const s = getSession();
  const isLocked = !s.token;
  const [items, setItems] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

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
                  {arr.map((p) => (
                    <div className="col-12" key={p.id}>
                      <div className="card post-card">
                        <div className="post-header">
                          <div className="post-avatar" aria-hidden="true">
                            {String(p.title || "A").trim().slice(0, 1).toUpperCase()}
                          </div>
                          <div>
                            <div className="h2" style={{ margin: 0 }}>
                              {p.title}
                            </div>
                            <div className="muted post-meta">
                              Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} • status: {p.status} • {p.rent_sale} •{" "}
                              {p.property_type} • {p.price_display} • {p.location_display}
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
                              const adv = String(p.adv_number || p.ad_number || p.id || "").trim();
                              const meta = [
                                adv ? `Ad #${adv}` : "",
                                `status: ${String(p.status || "").trim() || "unknown"}`,
                                String(p.rent_sale || "").trim(),
                                String(p.property_type || "").trim(),
                                String(p.price_display || "").trim(),
                                String(p.location_display || "").trim(),
                              ]
                                .filter(Boolean)
                                .join(" • ");
                              const img = p.images?.length ? toApiUrl(p.images[0].url) : "";
                              const text = [title, meta, img ? `Image: ${img}` : ""].filter(Boolean).join("\n");
                              const res = await sharePost({ title, text, url });
                              if (res === "copied") setMsg("Copied share text to clipboard.");
                            }}
                            style={{ padding: "8px 10px", minWidth: 44 }}
                          >
                            Share post
                          </button>
                          {(() => {
                            const pid = Number(p.id);
                            if (!Number.isInteger(pid) || pid <= 0) return null;
                            return <Link to={`/property/${pid}`}>Open ➜</Link>;
                          })()}
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
                              <img src={toApiUrl(p.images[0].url)} alt={`Ad ${p.id} media`} loading="lazy" />
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
                  ))}
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
    </div>
  );
}

