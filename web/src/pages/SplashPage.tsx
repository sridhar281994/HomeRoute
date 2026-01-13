import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getSession } from "../api";

export default function SplashPage() {
  const nav = useNavigate();
  useEffect(() => {
    const t = setTimeout(() => {
      const s = getSession();
      nav(s.token ? "/home" : "/welcome");
    }, 900);
    return () => clearTimeout(t);
  }, [nav]);

  return (
    <div className="panel" style={{ textAlign: "center", padding: 28 }}>
      <p className="h1" style={{ margin: 0 }}>
        Property Discovery  🏠✨
      </p>
      <p className="muted" style={{ marginTop: 10 }}>
        Loading...
      </p>
    </div>
  );
}

