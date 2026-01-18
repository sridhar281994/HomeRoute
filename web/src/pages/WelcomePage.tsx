import { Link, Navigate, useNavigate } from "react-router-dom";
import { getSession, setGuestSession } from "../api";

export default function WelcomePage() {
  const nav = useNavigate();
  const s = getSession();
  if (s.token || s.guest) return <Navigate to="/home" replace />;

  return (
    <div className="panel" style={{ textAlign: "center", padding: 28 }}>
      <p className="h1" style={{ margin: 0 }}>
        Find your perfect place  🏠✨
      </p>
      <p className="muted" style={{ marginTop: 10 }}>
        Browse properties for free. Login to contact owners. <span className="sparkle" aria-hidden="true" />
      </p>
      <div className="row" style={{ justifyContent: "center", marginTop: 14 }}>
        <Link to="/login">
          <button className="primary">Login</button>
        </Link>
        <Link to="/register">
          <button>Register ✨</button>
        </Link>
        <button
          onClick={() => {
            setGuestSession();
            nav("/home");
          }}
        >
          Continue as Guest
        </button>
      </div>
    </div>
  );
}

