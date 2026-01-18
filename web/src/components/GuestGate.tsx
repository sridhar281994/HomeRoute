import { Link, useNavigate } from "react-router-dom";
import { clearSession, getSession } from "../api";

type GuestGateProps = {
  title: string;
  message: string;
};

export default function GuestGate({ title, message }: GuestGateProps) {
  const nav = useNavigate();
  const s = getSession();
  const isGuest = Boolean(s.guest) && !s.token;

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          {title}
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      {isGuest ? (
        <div className="guest-pill" style={{ marginTop: 8 }}>
          Guest mode
        </div>
      ) : null}
      <p className="muted" style={{ marginTop: 10 }}>
        {message}
      </p>
      <div className="row" style={{ marginTop: 12 }}>
        <Link to="/login">
          <button className="primary">Login</button>
        </Link>
        <Link to="/register">
          <button>Register</button>
        </Link>
        <Link to="/home">
          <button>Continue browsing</button>
        </Link>
        {isGuest ? (
          <button
            className="danger"
            onClick={() => {
              clearSession();
              nav("/welcome");
            }}
          >
            Exit Guest
          </button>
        ) : null}
      </div>
    </div>
  );
}
