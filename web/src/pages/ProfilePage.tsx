import { useEffect, useState } from "react";
import {
  clearSession,
  deleteAccount,
  getMe,
  getSession,
  requestChangeEmailOtp,
  requestChangePhoneOtp,
  setSession,
  updateMe,
  uploadProfileImage,
  verifyChangeEmailOtp,
  verifyChangePhoneOtp,
} from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function ProfilePage() {
  const nav = useNavigate();
  const s = getSession();
  const [name, setName] = useState(s.user?.name || "");
  const [role] = useState((s.user?.role || "").toLowerCase() || "user");
  const [phone, setPhone] = useState((s.user as any)?.phone || "");
  const [email, setEmail] = useState(s.user?.email || "");
  const [profileImageUrl, setProfileImageUrl] = useState(((s.user as any)?.profile_image_url as string) || "");
  const [msg, setMsg] = useState("");

  const [newEmail, setNewEmail] = useState("");
  const [emailOtp, setEmailOtp] = useState("");
  const [newPhone, setNewPhone] = useState("");
  const [phoneOtp, setPhoneOtp] = useState("");

  useEffect(() => {
    if (!s.token) nav("/login");
  }, [nav, s.token]);

  useEffect(() => {
    if (!s.token) return;
    (async () => {
      try {
        const r = await getMe();
        const u = r.user as any;
        setName(u.name || "");
        setEmail(u.email || "");
        setPhone(u.phone || "");
        setProfileImageUrl(u.profile_image_url || "");
        setSession({ token: s.token, user: u });
      } catch (e: any) {
        setMsg(e.message || "Failed to load profile");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s.token]);

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Settings  ⚙️
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">Update your profile. Email/phone changes require OTP verification.</p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Profile photo</div>
            <div className="row" style={{ marginTop: 10, alignItems: "center" }}>
              {profileImageUrl ? (
                <img
                  src={profileImageUrl}
                  alt="Profile"
                  style={{ width: 92, height: 92, objectFit: "cover", borderRadius: 18, border: "1px solid rgba(255,255,255,.14)" }}
                />
              ) : (
                <div
                  style={{
                    width: 92,
                    height: 92,
                    borderRadius: 18,
                    border: "1px solid rgba(255,255,255,.14)",
                    background: "rgba(0,0,0,.20)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <span className="muted">No photo</span>
                </div>
              )}
              <div style={{ minWidth: 220 }}>
                <input
                  type="file"
                  accept="image/*"
                  onChange={async (e) => {
                    const f = e.target.files?.[0];
                    if (!f) return;
                    setMsg("");
                    try {
                      const r = await uploadProfileImage(f);
                      setProfileImageUrl((r.user as any)?.profile_image_url || "");
                      setSession({ token: getSession().token, user: r.user as any });
                      setMsg("Photo updated ✅");
                    } catch (err: any) {
                      setMsg(err.message || "Upload failed");
                    } finally {
                      e.currentTarget.value = "";
                    }
                  }}
                />
                <div className="muted" style={{ marginTop: 6 }}>
                  Upload a new image (JPG/PNG/WebP).
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="col-12 row">
          <div className="col-6" style={{ width: "100%" }}>
            <label className="muted">Role</label>
            <input value={role === "owner" ? "Owner" : "Customer"} disabled />
          </div>
        </div>

        <div className="col-6">
          <label className="muted">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="col-6 row" style={{ alignItems: "end" }}>
          <button
            className="primary"
            onClick={async () => {
              setMsg("");
              try {
                const r = await updateMe({ name: name.trim() });
                setSession({ token: getSession().token, user: r.user as any });
                setMsg("Saved ✅");
              } catch (e: any) {
                setMsg(e.message || "Save failed");
              }
            }}
          >
            Save name  💾
          </button>
        </div>

        <div className="col-12">
          <div className="card">
            <div className="h2">Email (OTP required)</div>
            <div className="grid" style={{ marginTop: 10 }}>
              <div className="col-6">
                <label className="muted">Current email</label>
                <input value={email} disabled />
              </div>
              <div className="col-6">
                <label className="muted">New email</label>
                <input value={newEmail} onChange={(e) => setNewEmail(e.target.value)} placeholder="new@email.com" />
              </div>
              <div className="col-12 row">
                <button
                  onClick={async () => {
                    setMsg("");
                    try {
                      const r = await requestChangeEmailOtp(newEmail.trim());
                      setMsg(r.message || "OTP sent");
                    } catch (e: any) {
                      setMsg(e.message || "Failed");
                    }
                  }}
                >
                  Send OTP
                </button>
                <div className="spacer" />
                <span className="muted">{msg}</span>
              </div>
              <div className="col-6">
                <label className="muted">OTP</label>
                <input value={emailOtp} onChange={(e) => setEmailOtp(e.target.value)} />
              </div>
              <div className="col-6 row" style={{ alignItems: "end" }}>
                <button
                  className="primary"
                  onClick={async () => {
                    setMsg("");
                    try {
                      const r = await verifyChangeEmailOtp(newEmail.trim(), emailOtp.trim());
                      setEmail((r.user as any).email || "");
                      setSession({ token: getSession().token, user: r.user as any });
                      setNewEmail("");
                      setEmailOtp("");
                      setMsg("Email updated ✅");
                    } catch (e: any) {
                      setMsg(e.message || "Failed");
                    }
                  }}
                >
                  Verify & Update
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="col-12">
          <div className="card">
            <div className="h2">Phone (OTP required)</div>
            <div className="grid" style={{ marginTop: 10 }}>
              <div className="col-6">
                <label className="muted">Current phone</label>
                <input value={phone} disabled />
              </div>
              <div className="col-6">
                <label className="muted">New phone</label>
                <input value={newPhone} onChange={(e) => setNewPhone(e.target.value)} placeholder="+91..." />
              </div>
              <div className="col-12 row">
                <button
                  onClick={async () => {
                    setMsg("");
                    try {
                      const r = await requestChangePhoneOtp(newPhone.trim());
                      setMsg(r.message || "OTP sent");
                    } catch (e: any) {
                      setMsg(e.message || "Failed");
                    }
                  }}
                >
                  Send OTP
                </button>
              </div>
              <div className="col-6">
                <label className="muted">OTP</label>
                <input value={phoneOtp} onChange={(e) => setPhoneOtp(e.target.value)} />
              </div>
              <div className="col-6 row" style={{ alignItems: "end" }}>
                <button
                  className="primary"
                  onClick={async () => {
                    setMsg("");
                    try {
                      const r = await verifyChangePhoneOtp(newPhone.trim(), phoneOtp.trim());
                      setPhone((r.user as any).phone || "");
                      setSession({ token: getSession().token, user: r.user as any });
                      setNewPhone("");
                      setPhoneOtp("");
                      setMsg("Phone updated ✅");
                    } catch (e: any) {
                      setMsg(e.message || "Failed");
                    }
                  }}
                >
                  Verify & Update
                </button>
              </div>
            </div>
          </div>
        </div>

        <div className="col-12 row">
          <button
            className="danger"
            onClick={async () => {
              const ok = window.confirm("Delete your account permanently? This cannot be undone.");
              if (!ok) return;
              setMsg("");
              try {
                await deleteAccount();
                clearSession();
                nav("/welcome");
              } catch (e: any) {
                setMsg(e.message || "Delete failed");
              }
            }}
          >
            Delete account
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

