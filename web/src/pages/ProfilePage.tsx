import { getSession } from "../api";

export default function ProfilePage() {
  const s = getSession();
  return (
    <div className="panel">
      <p className="h1">Profile / Settings</p>
      <p className="muted">This is the web equivalent of the mobile Settings screen.</p>
      <div className="card">
        <div className="h2">Current session</div>
        <pre style={{ whiteSpace: "pre-wrap", color: "rgba(255,255,255,.8)" }}>
          {JSON.stringify(s, null, 2)}
        </pre>
      </div>
    </div>
  );
}

