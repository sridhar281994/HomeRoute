import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import GuestGate from "../components/GuestGate";
import { getSession, getSubscriptionStatus } from "../api";

export default function SubscriptionPage() {
  const s = getSession();
  const isLocked = !s.token;
  const [status, setStatus] = useState("Loading...");
  const [provider, setProvider] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [msg, setMsg] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  async function load() {
    if (isLoading) return;
    setIsLoading(true);
    setMsg("");
    try {
      const r = await getSubscriptionStatus();
      setStatus(String(r.status || "inactive"));
      setProvider(String(r.provider || ""));
      setExpiresAt(String(r.expires_at || ""));
    } catch (e: any) {
      setMsg(e.message || "Failed to load subscription.");
      setStatus("Unavailable");
      setProvider("");
      setExpiresAt("");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    if (!s.token) return;
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.token]);

  if (isLocked) {
    return (
      <GuestGate
        title="Subscription"
        message="Login or register to view your subscription status."
      />
    );
  }

  const prettyExpires = expiresAt ? new Date(expiresAt).toLocaleString() : "—";

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Subscription
        </p>
        <div className="spacer" />
        <button onClick={load} disabled={isLoading}>
          Refresh
        </button>
        <Link to="/home">Back</Link>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Status</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {status}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              Provider: {provider || "—"}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              Expires: {prettyExpires}
            </div>
          </div>
        </div>
      </div>

      {msg ? <div className="muted" style={{ marginTop: 8 }}>{msg}</div> : null}
    </div>
  );
}
