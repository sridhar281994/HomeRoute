import { useEffect, useState } from "react";
import { getSession, requestOtp, setSession, verifyOtp } from "../api";
import { Link, Navigate, useNavigate } from "react-router-dom";
import PasswordField from "../components/PasswordField";

export default function LoginPage() {
  const nav = useNavigate();
  const s = getSession();
  if (s.token) {
    const role = String((s.user as any)?.role || "").toLowerCase();
    return <Navigate to={role === "admin" ? "/admin/review" : "/home"} replace />;
  }

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [msg, setMsg] = useState<string>("");

  return (
    <div className="panel">
      <div className="row" style={{ alignItems: "baseline" }}>
        <p className="h1" style={{ margin: 0 }}>
          Login
        </p>
        <div className="spacer" />
        <Link className="muted" to="/forgot" style={{ textDecoration: "none" }}>
          Forgot password?
        </Link>
      </div>
      <p className="muted">Request an OTP, then verify to login.</p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Email/Username</label>
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
        </div>
        <div className="col-6">
          <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="current-password" />
        </div>
        <div className="col-12 row">
          <button
            onClick={async () => {
              try {
                const r = await requestOtp(identifier, password);
                setMsg(r.message || "OTP sent.");
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Request OTP
          </button>
          <div className="spacer" />
          <span className="muted">{msg}</span>
        </div>
        <div className="col-6">
          <label className="muted">OTP</label>
          <input value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric" />
        </div>
        <div className="col-6 row" style={{ alignItems: "end" }}>
          <button
            className="primary"
            onClick={async () => {
              try {
                const r = await verifyOtp(identifier, password, otp);
                setSession({ token: r.access_token, user: r.user });
                const role = String((r.user as any)?.role || "").toLowerCase();
                nav(role === "admin" ? "/admin/review" : "/home");
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Verify & Login
          </button>
        </div>
      </div>
    </div>
  );
}

