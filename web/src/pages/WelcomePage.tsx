import { Link } from "react-router-dom";

export default function WelcomePage() {
  return (
    <div className="panel" style={{ textAlign: "center", padding: 28 }}>
      <p className="h1" style={{ margin: 0 }}>
        Find your perfect place  🏠✨
      </p>
      <p className="muted" style={{ marginTop: 10 }}>
        Browse properties for free. Unlock contact with a subscription. <span className="sparkle" aria-hidden="true" />
      </p>
      <div className="row" style={{ justifyContent: "center", marginTop: 14 }}>
        <Link to="/login">
          <button className="primary">Login</button>
        </Link>
        <Link to="/register">
          <button>Register ✨</button>
        </Link>
        <Link to="/home">
          <button>Continue as Guest</button>
        </Link>
      </div>
    </div>
  );
}

