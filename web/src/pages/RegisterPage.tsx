import { useMemo, useState } from "react";
import { registerUser } from "../api";
import { INDIA_STATES } from "../indiaStates";
import { districtsForState } from "../indiaDistricts";
import { Link, useNavigate } from "react-router-dom";

const OWNER_CATEGORIES = [
  // Property & Real Estate
  "Apartment Owner",
  "Villa Owner",
  "Plot Owner",
  "PG Owner",
  "Marriage Hall Owner",
  "Party Hall Owner",
  // Construction & Materials
  "Retailer / Hardware Shop",
  "Steel Supplier",
  "Brick Supplier",
  "Sand Supplier",
  "M-Sand Supplier",
  "Cement Supplier",
  // Services & Workforce
  "Interior Designer",
  "Carpenter / Wood Works",
  "Mason / Labor Contractor",
  "Electrician",
  "Plumber",
  "Painter",
  "Gardener / Landscaping",
  "Cleaning Services",
] as const;

export default function RegisterPage() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState(INDIA_STATES[0] || "");
  const [district, setDistrict] = useState("");
  const [role, setRole] = useState<"customer" | "owner">("customer");
  const [ownerCategory, setOwnerCategory] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string>("");

  const stateOptions = useMemo(() => INDIA_STATES, []);
  const districtOptions = useMemo(() => districtsForState(state), [state]);

  return (
    <div className="panel">
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
            <select value={ownerCategory} onChange={(e) => setOwnerCategory(e.target.value)}>
              <option value="">Select category</option>
              {OWNER_CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
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
          <label className="muted">Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="col-12 row">
          <button
            className="primary"
            onClick={async () => {
              try {
                if (!district) throw new Error("Please select your district.");
                const digits = (phone || "").replace(/\D/g, "");
                if (digits.length < 8 || digits.length > 15) throw new Error("Enter a valid phone number.");
                if (role === "owner" && !ownerCategory) throw new Error("Please select your owner category.");
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

