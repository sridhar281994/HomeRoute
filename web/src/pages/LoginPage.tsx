import { useEffect, useRef, useState } from "react";
import { getSession, loginWithGoogle, requestOtp, setSession, verifyOtp } from "../api";
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
  const googleBtnRef = useRef<HTMLDivElement | null>(null);

  const googleClientId =
    String((import.meta as any).env?.VITE_GOOGLE_CLIENT_ID || "").trim() ||
    "333176294914-nusbltfj219k3ou30dnqluvcqsvsr93d.apps.googleusercontent.com";

  useEffect(() => {
    let cancelled = false;
    let rendered = false;
    let tries = 0;

    const tick = () => {
      if (cancelled || rendered) return;
      const api = window.google?.accounts?.id;
      if (!api || !googleBtnRef.current) {
        if (tries++ < 50) setTimeout(tick, 100);
        return;
      }

      try {
        api.initialize({
          client_id: googleClientId,
          callback: async (resp) => {
            try {
              const credential = String(resp?.credential || "").trim();
              if (!credential) throw new Error("Google Sign-In did not return a credential.");
              const r = await loginWithGoogle(credential);
              setSession({ token: r.access_token, user: r.user });
              const role = String((r.user as any)?.role || "").toLowerCase();
              nav(role === "admin" ? "/admin/review" : "/home");
            } catch (e: any) {
              setMsg(e?.message || "Google login failed.");
            }
          },
        });
        api.renderButton(googleBtnRef.current, {
          theme: "outline",
          size: "large",
          shape: "pill",
          text: "continue_with",
          width: 320,
        });
        rendered = true;
      } catch (e: any) {
        setMsg(e?.message || "Google Sign-In initialization failed.");
      }
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [googleClientId, nav]);

  return (
    <div className="panel">
      <div className="auth-header">
        <div className="auth-title">flatnow.in</div>
        <div className="auth-subtitle">UNLOCK your path</div>
      </div>
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
        <div className="col-12">
          <label className="muted">Google</label>
          <div ref={googleBtnRef} />
        </div>
        <div className="col-6">
          <label className="muted">Email / Username / Phone</label>
          <input placeholder="Email, username, or phone" value={identifier} onChange={(e) => setIdentifier(e.target.value)} />
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

