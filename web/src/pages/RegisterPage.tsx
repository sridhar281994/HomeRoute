import { useMemo, useState } from "react";
import { registerUser } from "../api";
import { INDIA_STATES } from "../indiaStates";
import { Link, useNavigate } from "react-router-dom";

export default function RegisterPage() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState(INDIA_STATES[0] || "");
  const [gender, setGender] = useState("male");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string>("");

  const stateOptions = useMemo(() => INDIA_STATES, []);

  return (
    <div className="panel">
      <p className="h1">Register (India only)</p>
      <p className="muted">
        Already have an account? <Link to="/login">Login</Link>
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Full name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">State</label>
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {stateOptions.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Gender</label>
          <select value={gender} onChange={(e) => setGender(e.target.value)}>
            <option value="male">male</option>
            <option value="female">female</option>
            <option value="cross">cross</option>
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
                await registerUser({ email, username, password, name, state, gender });
                nav("/login");
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Create account
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

