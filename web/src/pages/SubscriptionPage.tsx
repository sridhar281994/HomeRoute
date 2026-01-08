import { useEffect, useState } from "react";
import { subscriptionStatus } from "../api";

export default function SubscriptionPage() {
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
    load();
  }, []);

  return (
    <div className="panel">
      <p className="h1">Subscription</p>
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

