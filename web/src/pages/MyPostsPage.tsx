import { useEffect, useMemo, useState } from "react";
import { getSession, ownerDeleteProperty, ownerListProperties } from "../api";
import { Link, useNavigate } from "react-router-dom";

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
    if (!s.token) nav("/login");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.token]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grouped = useMemo(() => groupByStatus(items), [items]);
  const order = ["pending", "approved", "rejected", "suspended", "unknown"];

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
                      <div className="card">
                        <div className="row">
                          <div>
                            <div className="h2">
                              #{p.id} • {p.title}
                            </div>
                            <div className="muted">
                              {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display}
                              {p.created_at ? ` • ${new Date(p.created_at).toLocaleString()}` : ""}
                            </div>
                          </div>
                          <div className="spacer" />
                          {String(p.status || "").toLowerCase() === "approved" ? <Link to={`/property/${p.id}`}>Open ➜</Link> : null}
                          <button
                            className="danger"
                            onClick={async () => {
                              const ok = window.confirm(`Delete post #${p.id}? This cannot be undone.`);
                              if (!ok) return;
                              try {
                                await ownerDeleteProperty(Number(p.id));
                                setMsg(`Deleted post #${p.id}`);
                                load();
                              } catch (e: any) {
                                setMsg(e.message || "Delete failed");
                              }
                            }}
                          >
                            Remove
                          </button>
                        </div>
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

