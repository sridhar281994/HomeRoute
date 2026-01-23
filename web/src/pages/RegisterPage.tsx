import { useEffect, useState } from "react";
import { getCategoryCatalog, getSession, listLocationDistricts, listLocationStates, registerUser } from "../api";
import { Link, Navigate, useNavigate } from "react-router-dom";
import PasswordField from "../components/PasswordField";

export default function RegisterPage() {
  const nav = useNavigate();
  const s = getSession();
  if (s.token) return <Navigate to="/home" replace />;

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState("");
  const [district, setDistrict] = useState("");
  const [role, setRole] = useState<"customer" | "owner">("customer");
  const [ownerCategory, setOwnerCategory] = useState("");
  const [ownerCategories, setOwnerCategories] = useState<string[]>([]);
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string>("");

  const [stateOptions, setStateOptions] = useState<string[]>([]);
  const [districtOptions, setDistrictOptions] = useState<string[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const r = await listLocationStates();
        const states = (r.items || []).map((x) => String(x || "").trim()).filter(Boolean);
        setStateOptions(states);
        // Choose a sensible default so District dropdown can work immediately.
        if (!state) {
          const preferred = states.includes("Tamil Nadu") ? "Tamil Nadu" : states[0] || "";
          setState(preferred);
        }
      } catch {
        setStateOptions([]);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!state) {
      setDistrictOptions([]);
      setDistrict("");
      return;
    }
    (async () => {
      try {
        const r = await listLocationDistricts(state);
        setDistrictOptions((r.items || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        setDistrictOptions([]);
      }
    })();
  }, [state]);

  useEffect(() => {
    (async () => {
      try {
        const c = await getCategoryCatalog();
        setOwnerCategories((c.owner_categories || []).map((x) => String(x || "").trim()).filter(Boolean));
      } catch {
        // Non-fatal: registration can still proceed without category metadata.
        setOwnerCategories([]);
      }
    })();
  }, []);

  return (
    <div className="panel">
      <div className="auth-header">
        <div className="auth-title">flatnow.in</div>
        <div className="auth-subtitle">UNLOCK your path</div>
      </div>
      <p className="h1">Create Account  ✨</p>
      <p className="muted">
        Already have an account? <Link to="/login">Login</Link>
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Full name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Phone number</label>
          <input value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="Eg: 9876543210" />
        </div>
        <div className="col-6">
          <label className="muted">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Role</label>
          <div className="row" style={{ gap: 10 }}>
            <button className={`chip ${role === "owner" ? "chip-on" : ""}`} onClick={() => setRole("owner")}>
              Owner  🏢
            </button>
            <button
              className={`chip ${role === "customer" ? "chip-on" : ""}`}
              onClick={() => setRole("customer")}
            >
              Customer  🧍
            </button>
          </div>
        </div>
        {role === "owner" ? (
          <div className="col-12">
            <label className="muted">Owner category</label>
            {ownerCategories.length ? (
              <select value={ownerCategory} onChange={(e) => setOwnerCategory(e.target.value)}>
                <option value="">Select category</option>
                {ownerCategories.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            ) : (
              <>
                <input value={ownerCategory} onChange={(e) => setOwnerCategory(e.target.value)} placeholder="Enter category" />
                <div className="muted" style={{ marginTop: 6 }}>
                  Category list is loading.
                </div>
              </>
            )}
          </div>
        ) : null}
        <div className="col-6">
          <label className="muted">State</label>
          <select
            value={state}
            onChange={(e) => {
              setState(e.target.value);
              setDistrict("");
            }}
          >
            <option value="">Select state</option>
            {stateOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">District</label>
          <select value={district} onChange={(e) => setDistrict(e.target.value)}>
            <option value="">Select District</option>
            {districtOptions.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="new-password" />
        </div>
        <div className="col-12 row">
          <button
            className="primary"
            onClick={async () => {
              try {
                if (!state) throw new Error("Please select your state.");
                if (!district) throw new Error("Please select your district.");
                const digits = (phone || "").replace(/\D/g, "");
                if (digits.length < 8 || digits.length > 15) throw new Error("Enter a valid phone number.");
                if (role === "owner" && !ownerCategory) throw new Error("Please select your Owner category.");
                await registerUser({
                  email,
                  phone,
                  password,
                  name,
                  state,
                  district,
                  role: role === "owner" ? "owner" : "user",
                  owner_category: role === "owner" ? ownerCategory : "",
                });
                nav("/login");
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Create account  ✅
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

