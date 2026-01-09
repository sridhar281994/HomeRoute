import { useEffect, useMemo, useState } from "react";
import { getSession, setSession } from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function ProfilePage() {
  const nav = useNavigate();
  const s = getSession();
  const [name, setName] = useState(s.user?.name || "");
  const [phone, setPhone] = useState((s.user as any)?.phone || "");
  const [email, setEmail] = useState(s.user?.email || "");
  const [imageUrl, setImageUrl] = useState(((s.user as any)?.image_url as string) || "");
  const [locationsText, setLocationsText] = useState<string>(((s.user as any)?.locations || []).join("\n"));
  const [msg, setMsg] = useState("");

  const locations = useMemo(
    () =>
      (locationsText || "")
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean),
    [locationsText]
  );

  useEffect(() => {
    if (!s.token) nav("/login");
  }, [nav, s.token]);

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Settings  ⚙️
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">Edit your profile and add multiple locations/branches.</p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Phone number</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Profile image URL</label>
          <input value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://..." />
        </div>
        <div className="col-12">
          <label className="muted">Branches / Locations (one per line)</label>
          <textarea
            value={locationsText}
            onChange={(e) => setLocationsText(e.target.value)}
            rows={5}
            placeholder={"Eg:\nChennai - T Nagar\nCoimbatore - RS Puram"}
          />
        </div>

        <div className="col-12 row">
          <button
            className="primary"
            onClick={() => {
              setMsg("");
              const curr = getSession();
              if (!curr.token) return nav("/login");

              const nextUser = {
                ...(curr.user || {}),
                name: name.trim(),
                email: email.trim(),
                phone: phone.trim(),
                image_url: imageUrl.trim(),
                locations,
              } as any;

              setSession({ token: curr.token, user: nextUser });
              setMsg("Saved ✅");
            }}
          >
            Save settings  💾
          </button>
          <span className="muted">{msg}</span>
        </div>

        {imageUrl ? (
          <div className="col-12">
            <div className="card">
              <div className="h2">Preview</div>
              <div style={{ marginTop: 10 }}>
                <img
                  src={imageUrl}
                  alt="Profile preview"
                  style={{ maxWidth: 240, borderRadius: 16, border: "1px solid rgba(255,255,255,.14)" }}
                  onError={() => setMsg("Image URL not reachable.")}
                />
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

