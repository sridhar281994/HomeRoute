import { Link, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { clearSession, getSession } from "./api";
import SplashPage from "./pages/SplashPage";
import WelcomePage from "./pages/WelcomePage";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import HomePage from "./pages/HomePage";
import PropertyPage from "./pages/PropertyPage";
import SubscriptionPage from "./pages/SubscriptionPage";
import ProfilePage from "./pages/ProfilePage";
import OwnerAddPage from "./pages/OwnerAddPage";
import AdminReviewPage from "./pages/AdminReviewPage";

export default function App() {
  const loc = useLocation();
  const nav = useNavigate();
  const s = getSession();
  const role = (s.user?.role || "").toLowerCase();
  const isLoggedIn = !!s.token;
  const isHome = loc.pathname === "/home";

  return (
    <div className="shell">
      {!isHome ? <div className="app-bg" aria-hidden="true" /> : null}
      <div className="panel nav row" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 10 }}>
          <div className="h2">Property Discovery (India)  🏠✨</div>
        </div>
        <div className="spacer" />
        <div className="row nav" style={{ gap: 10 }}>
          <Link to="/home">Home</Link>
          {isLoggedIn ? (
            <>
              <Link to="/subscription">Subscription</Link>
              <Link to="/profile">Settings</Link>
              {role === "owner" ? <Link to="/owner/add">Owner</Link> : null}
            </>
          ) : null}
          {!isLoggedIn ? (
            <>
              <Link to="/login">Login</Link>
              <Link to="/register">Register</Link>
            </>
          ) : (
            <button
              className="danger"
              onClick={() => {
                clearSession();
                nav("/login");
              }}
            >
              Logout
            </button>
          )}
        </div>
      </div>

      <Routes>
        <Route path="/" element={<SplashPage />} />
        <Route path="/welcome" element={<WelcomePage />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/property/:id" element={<PropertyPage />} />
        <Route path="/subscription" element={<SubscriptionPage />} />
        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/owner/add" element={<OwnerAddPage />} />
        <Route path="/admin/review" element={<AdminReviewPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
    </div>
  );
}

