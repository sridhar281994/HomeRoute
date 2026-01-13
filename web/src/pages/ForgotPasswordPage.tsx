import { useState } from "react";
import { forgotPasswordRequestOtp, forgotPasswordReset } from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function ForgotPasswordPage() {
  const nav = useNavigate();
  const [stage, setStage] = useState<"request" | "reset">("request");
  const [identifier, setIdentifier] = useState("");
  const [otp, setOtp] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [msg, setMsg] = useState("");

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Reset password
        </p>
        <div className="spacer" />
        <Link to="/login">Back</Link>
      </div>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Email/Username</label>
          <input value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
        </div>

        {stage === "request" ? (
          <div className="col-6 row" style={{ alignItems: "end" }}>
            <button
              className="primary"
              onClick={async () => {
                setMsg("");
                try {
                  const r = await forgotPasswordRequestOtp(identifier);
                  setMsg(r.message || "OTP sent.");
                  setStage("reset");
                } catch (e: any) {
                  setMsg(e.message || "Failed");
                }
              }}
            >
              Request OTP
            </button>
          </div>
        ) : (
          <>
            <div className="col-6">
              <label className="muted">OTP</label>
              <input value={otp} onChange={(e) => setOtp(e.target.value)} />
            </div>
            <div className="col-6">
              <label className="muted">New password</label>
              <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
            </div>
            <div className="col-12 row">
              <button
                className="primary"
                onClick={async () => {
                  setMsg("");
                  try {
                    await forgotPasswordReset(identifier, otp, newPassword);
                    setMsg("Password updated. Please login.");
                    setTimeout(() => nav("/login"), 600);
                  } catch (e: any) {
                    setMsg(e.message || "Failed");
                  }
                }}
              >
                Verify OTP & Reset
              </button>
              <button
                onClick={() => {
                  setStage("request");
                  setOtp("");
                  setNewPassword("");
                }}
              >
                Back to OTP request
              </button>
            </div>
          </>
        )}

        <div className="col-12">
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

