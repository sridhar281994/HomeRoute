import { useEffect, useState } from "react";
import { adminApprove, adminPending, adminReject } from "../api";

export default function AdminReviewPage() {
  const [items, setItems] = useState<any[]>([]);
  const [msg, setMsg] = useState("");

  async function load() {
    setMsg("");
    try {
      const res = await adminPending();
      setItems(res.items || []);
    } catch (e: any) {
      setMsg(e.message || "Failed");
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="panel">
      <p className="h1">Admin: Review New Listings</p>
      <p className="muted">
        Login with <b>Admin</b> / <b>Admin@123</b> to use these endpoints.
      </p>
      <div className="row">
        <button className="primary" onClick={load}>
          Refresh
        </button>
        <span className="muted">{msg}</span>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        {items.map((p) => (
          <div key={p.id} className="col-12">
            <div className="card">
              <div className="row">
                <div>
                  <div className="h2">
                    #{p.id} — {p.title}
                  </div>
                  <div className="muted">
                    {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display} • status: {p.status}
                  </div>
                </div>
                <div className="spacer" />
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

