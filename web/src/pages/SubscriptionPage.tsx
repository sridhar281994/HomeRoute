import { useEffect, useState } from "react";
import { getSession, subscriptionStatus } from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function SubscriptionPage() {
  const nav = useNavigate();
  const [status, setStatus] = useState("Unknown");
  const [msg, setMsg] = useState("");

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
        Payments are handled by <b>Google Play Billing</b>. This web UI only demonstrates the paywall + status check.
      </p>
      <div className="row">
        <button className="primary" onClick={load}>
          Refresh status
        </button>
        <span className="muted">{msg}</span>
      </div>
    </div>
  );
}

