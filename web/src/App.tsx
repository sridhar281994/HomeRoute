import { Link, Route, Routes, useNavigate } from "react-router-dom";
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
  const nav = useNavigate();
  const s = getSession();
  const role = s.user?.role || "guest";

  return (
    <div className="shell">
      <div className="panel nav row" style={{ marginBottom: 14 }}>
        <div className="row" style={{ gap: 10 }}>
          <div className="h2">Property Discovery (India)</div>
          <span className="muted">Role: {role}</span>
        </div>
        <div className="spacer" />
        <div className="row nav" style={{ gap: 10 }}>
          <Link to="/home">Home</Link>
          <Link to="/subscription">Subscription</Link>
          <Link to="/profile">Profile</Link>
          <Link to="/owner/add">Owner</Link>
          <Link to="/admin/review">Admin</Link>
          {!s.token ? (
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

