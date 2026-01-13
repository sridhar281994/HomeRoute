import { useState } from "react";
import { requestOtp, setSession, verifyOtp } from "../api";
import { useNavigate } from "react-router-dom";

export default function LoginPage() {
  const nav = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [msg, setMsg] = useState<string>("");

  return (
    <div className="panel">
      <p className="h1">Login</p>
      <p className="muted">Request an OTP, then verify to login.</p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Email/Username</label>
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
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
          <input value={otp} onChange={(e) => setOtp(e.target.value)} />
        </div>
        <div className="col-6 row" style={{ alignItems: "end" }}>
          <button
            className="primary"
            onClick={async () => {
              try {
                const r = await verifyOtp(identifier, password, otp);
                setSession({ token: r.access_token, user: r.user });
                nav("/home");
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

