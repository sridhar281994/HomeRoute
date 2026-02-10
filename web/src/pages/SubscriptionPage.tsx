import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import GuestGate from "../components/GuestGate";
import { getSession, getSubscriptionStatus, getSubscriptionSummary } from "../api";

export default function SubscriptionPage() {
  const s = getSession();
  const isLocked = !s.token;
  const [status, setStatus] = useState("Loading...");
  const [provider, setProvider] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [msg, setMsg] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [summary, setSummary] = useState<{
    window_days: number;
    service_requested: number;
    earned: number;
    merchant_fee: number;
  } | null>(null);

  async function load() {
    if (isLoading) return;
    setIsLoading(true);
    setMsg("");
    try {
      const r = await getSubscriptionStatus();
      setStatus(String(r.status || "inactive"));
      setProvider(String(r.provider || ""));
      setExpiresAt(String(r.expires_at || ""));
      const s2 = await getSubscriptionSummary({ window_days: 30 });
      setSummary({
        window_days: Number(s2.window_days || 30),
        service_requested: Number(s2.service_requested || 0),
        earned: Number(s2.earned || 0),
        merchant_fee: Number(s2.merchant_fee || 0),
      });
    } catch (e: any) {
      setMsg(e.message || "Failed to load subscription.");
      setStatus("Unavailable");
      setProvider("");
      setExpiresAt("");
      setSummary(null);
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

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <button className="sub-plan" type="button">
            <div className="sub-plan-title">FREE - 0</div>
            <div className="sub-plan-desc">Unlock 30 owner/service contacts</div>
          </button>
        </div>
        <div className="col-6">
          <button className="sub-plan" type="button">
            <div className="sub-plan-title">INSTANT - ₹10</div>
            <div className="sub-plan-desc">Unlock 60 owner/service contacts</div>
          </button>
        </div>
        <div className="col-6">
          <button className="sub-plan" type="button">
            <div className="sub-plan-title">SMART - ₹50</div>
            <div className="sub-plan-desc">Unlock 200 contacts</div>
          </button>
        </div>
        <div className="col-6">
          <button className="sub-plan" type="button">
            <div className="sub-plan-title">BUSINESS - ₹150</div>
            <div className="sub-plan-desc">Unlimited contact unlocks/Month</div>
          </button>
        </div>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Summary</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Last {summary?.window_days ?? 30} days
            </div>
            <div className="muted" style={{ marginTop: 10 }}>
              Service requested: {summary ? summary.service_requested : "—"}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              Earned: {summary ? `₹${summary.earned}` : "—"}
            </div>
            <div className="muted" style={{ marginTop: 6 }}>
              Merchant fee: {summary ? `₹${summary.merchant_fee}` : "—"}
            </div>
          </div>
        </div>
      </div>

      {msg ? <div className="muted" style={{ marginTop: 8 }}>{msg}</div> : null}
    </div>
  );
}
