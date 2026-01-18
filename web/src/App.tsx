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
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import MyPostsPage from "./pages/MyPostsPage";

export default function App() {
  const loc = useLocation();
  const nav = useNavigate();
  const s = getSession();
  const role = (s.user?.role || "").toLowerCase();
  const isLoggedIn = !!s.token;
  const isGuest = !!s.guest && !isLoggedIn;

  return (
    <div className="shell">
      <div className="app-bg" aria-hidden="true" />
      <div className="panel topbar" style={{ marginBottom: 14 }}>
        <div className="topbar-brand">
          <div className="h2">QuickRent</div>
          {isGuest ? <div className="guest-pill">Guest mode</div> : null}
        </div>
        <div className="spacer" />
        <div className="topbar-links">
          <Link to="/home">Home</Link>
          {role === "admin" ? <Link to="/admin/review">Admin Review</Link> : null}
          <Link to="/subscription">Subscription</Link>
          <Link to="/myposts">My Posts</Link>
          <Link to="/profile">Settings</Link>
          <Link to="/owner/add">Publish Ad</Link>
          {!isLoggedIn ? (
            <>
              <Link to="/login">Login</Link>
              <Link to="/register">Register</Link>
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
        <Route path="/myposts" element={<MyPostsPage />} />
        <Route path="/admin/review" element={<AdminReviewPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot" element={<ForgotPasswordPage />} />
      </Routes>
    </div>
  );
}

