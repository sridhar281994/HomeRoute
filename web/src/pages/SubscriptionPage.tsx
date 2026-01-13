import { useEffect, useState } from "react";
import { getSession, subscriptionStatus } from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function SubscriptionPage() {
  const nav = useNavigate();
  const [status, setStatus] = useState("Unknown");
  const [msg, setMsg] = useState("");
  const plans = [
    { name: "Aggressive", price: "₹10", productId: "aggressive_10" },
    { name: "Instant", price: "₹79", productId: "instant_79" },
    { name: "Smart", price: "₹199 / month", productId: "smart_monthly_199" },
    { name: "Business", price: "₹499 / 3 months", productId: "business_quarterly_499" },
  ];

  async function load() {
    setMsg("");
    try {
      const s = await subscriptionStatus();
      setStatus((s.status || "inactive").toUpperCase());
    } catch (e: any) {
      setMsg(e.message || "Failed");
    }
  }

  useEffect(() => {
    if (!getSession().token) {
      nav("/login");
      return;
    }
    load();
  }, []);

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Subscription  💎
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">Status: {status}</p>
      <p className="muted">
        Payments are handled by <b>Google Play Billing</b>. This web UI only shows the available plans + status check.
      </p>
      <div className="card" style={{ marginTop: 10 }}>
        <div className="h2">Plans</div>
        <div className="grid" style={{ marginTop: 10 }}>
          {plans.map((p) => (
            <div className="col-6" key={p.productId}>
              <div className="card">
                <div className="row">
                  <div>
                    <div className="h2">{p.name}</div>
                    <div className="muted">{p.price}</div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      Product: {p.productId}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="row">
        <button className="primary" onClick={load}>
          Refresh status
        </button>
        <span className="muted">{msg}</span>
      </div>
    </div>
  );
}

