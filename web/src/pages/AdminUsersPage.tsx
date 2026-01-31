import { useEffect, useMemo, useState } from "react";
import { adminApproveUser, adminGetUser, adminListUsers, adminMarkSpam, adminSuspendUser, getSession } from "../api";
import GuestGate from "../components/GuestGate";
import { Link } from "react-router-dom";
import { toApiUrl } from "../api";

export default function AdminUsersPage() {
  const s = getSession();
  const role = String(s.user?.role || "").toLowerCase();
  const isAdmin = !!s.token && role === "admin";

  const [q, setQ] = useState("");
  const [msg, setMsg] = useState("");
  const [items, setItems] = useState<any[]>([]);

  const [activeUserId, setActiveUserId] = useState<number | null>(null);
  const [activeUser, setActiveUser] = useState<any | null>(null);
  const [activePosts, setActivePosts] = useState<any[]>([]);
  const [loadingUser, setLoadingUser] = useState(false);

  async function loadUsers() {
    setMsg("");
    try {
      const r = await adminListUsers({ q: q.trim() || undefined, limit: 200 });
      setItems(r.items || []);
    } catch (e: any) {
      setMsg(e.message || "Failed to load users");
    }
  }

  async function loadUser(userId: number) {
    setLoadingUser(true);
    setMsg("");
    try {
      const r = await adminGetUser(userId);
      setActiveUser(r.user || null);
      setActivePosts(r.posts || []);
    } catch (e: any) {
      setMsg(e.message || "Failed to load user");
    } finally {
      setLoadingUser(false);
    }
  }

  useEffect(() => {
    if (!isAdmin) return;
    loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  const activeUserStatus = String(activeUser?.approval_status || "").toLowerCase();
  const isSuspended = activeUserStatus === "suspended";

  const postsByStatus = useMemo(() => {
    const out: Record<string, number> = {};
    for (const p of activePosts) {
      const st = String(p.status || "unknown").toLowerCase();
      out[st] = (out[st] || 0) + 1;
    }
    return out;
  }, [activePosts]);

  if (!isAdmin) {
    return <GuestGate title="User Administration" message="Admin access required." />;
  }

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          User Administration
        </p>
        <div className="spacer" />
        <Link to="/admin/review">Back to Admin Review</Link>
      </div>

      <div className="row" style={{ marginTop: 10, gap: 10, alignItems: "center" }}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search name / email / phone / username"
          style={{ flex: 1, minWidth: 220 }}
        />
        <button onClick={loadUsers}>Search</button>
      </div>

      {msg ? (
        <div className="muted" style={{ marginTop: 10 }}>
          {msg}
        </div>
      ) : null}

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Users</div>
            <div className="muted" style={{ marginTop: 6 }}>
              Tap a user to view posts and actions.
            </div>

            <div className="grid" style={{ marginTop: 10 }}>
              {(items || []).map((u) => {
                const uid = Number(u.id);
                const selected = activeUserId === uid;
                const status = String(u.approval_status || "").trim() || "approved";
                return (
                  <div className="col-12" key={uid}>
                    <button
                      type="button"
                      className="card"
                      style={{
                        width: "100%",
                        textAlign: "left",
                        border: selected ? "1px solid rgba(255,255,255,.55)" : "1px solid rgba(255,255,255,.14)",
                      }}
                      onClick={async () => {
                        setActiveUserId(uid);
                        await loadUser(uid);
                      }}
                    >
                      <div className="row">
                        <div>
                          <div className="h2" style={{ margin: 0 }}>
                            {u.name || "—"}{" "}
                            <span className="muted" style={{ fontSize: 14 }}>
                              (#{uid})
                            </span>
                          </div>
                          <div className="muted">
                            {u.email || "—"} {u.phone ? ` • ${u.phone}` : ""} {u.username ? ` • ${u.username}` : ""}
                          </div>
                          <div className="muted">
                            role: {u.role || "user"} • status: {status} • total posts: {Number(u.total_posts || 0)}
                          </div>
                        </div>
                        <div className="spacer" />
                        <div className="muted" style={{ textAlign: "right" }}>
                          {u.created_at ? new Date(u.created_at).toLocaleString() : ""}
                        </div>
                      </div>
                    </button>
                  </div>
                );
              })}
              {!items?.length ? (
                <div className="col-12 muted" style={{ marginTop: 8 }}>
                  No users found.
                </div>
              ) : null}
            </div>
          </div>
        </div>

        {activeUserId != null ? (
          <div className="col-12">
            <div className="card">
              <div className="row">
                <div>
                  <div className="h2" style={{ margin: 0 }}>
                    {activeUser?.name || "User"}{" "}
                    <span className="muted" style={{ fontSize: 14 }}>
                      (#{activeUserId})
                    </span>
                  </div>
                  <div className="muted">
                    {activeUser?.email || "—"} {activeUser?.phone ? ` • ${activeUser.phone}` : ""} • role: {activeUser?.role || "user"} • status:{" "}
                    {activeUser?.approval_status || "approved"}
                  </div>
                  {activeUser?.approval_reason ? <div className="muted">reason: {activeUser.approval_reason}</div> : null}
                  <div className="muted" style={{ marginTop: 6 }}>
                    Posts: {activePosts.length} (approved: {postsByStatus.approved || 0}, pending: {postsByStatus.pending || 0}, suspended:{" "}
                    {postsByStatus.suspended || 0})
                  </div>
                </div>
                <div className="spacer" />
                <div className="row" style={{ gap: 10 }}>
                  {isSuspended ? (
                    <button
                      className="primary"
                      onClick={async () => {
                        try {
                          await adminApproveUser(activeUserId);
                          setMsg("User enabled.");
                          await loadUsers();
                          await loadUser(activeUserId);
                        } catch (e: any) {
                          setMsg(e.message || "Enable failed");
                        }
                      }}
                    >
                      Enable user
                    </button>
                  ) : (
                    <button
                      className="danger"
                      onClick={async () => {
                        const reason = window.prompt("Disable this user? Reason (optional):", "Disabled by admin") || "";
                        try {
                          await adminSuspendUser(activeUserId, reason);
                          setMsg("User disabled.");
                          await loadUsers();
                          await loadUser(activeUserId);
                        } catch (e: any) {
                          setMsg(e.message || "Disable failed");
                        }
                      }}
                    >
                      Disable user
                    </button>
                  )}
                </div>
              </div>

              <div className="h2" style={{ marginTop: 12 }}>
                Posts
              </div>

              {loadingUser ? <div className="muted">Loading…</div> : null}

              <div className="grid" style={{ marginTop: 10 }}>
                {activePosts.map((p) => {
                  const pid = Number(p.id);
                  const url = Number.isInteger(pid) && pid > 0 ? `${window.location.origin}/property/${pid}` : window.location.href;
                  const isSpam = String(p.moderation_reason || "").toUpperCase().includes("SPAM") || String(p.status || "").toLowerCase() === "suspended";
                  const thumb = p.images?.length ? toApiUrl(p.images[0].url) : "";
                  return (
                    <div className="col-12" key={pid}>
                      <div className="card post-card" style={{ position: "relative" }}>
                        {isSpam ? (
                          <div
                            style={{
                              position: "absolute",
                              top: 10,
                              right: 10,
                              padding: "6px 10px",
                              borderRadius: 10,
                              border: "1px solid rgba(255,255,255,.35)",
                              background: "rgba(239,68,68,.18)",
                              color: "rgba(255,255,255,.92)",
                              fontWeight: 700,
                              letterSpacing: 1,
                            }}
                          >
                            SPAM
                          </div>
                        ) : null}
                        <div className="row" style={{ alignItems: "center" }}>
                          <div>
                            <div className="h2" style={{ margin: 0 }}>
                              Ad #{String(p.adv_number || p.ad_number || p.id || "").trim()} — {p.title}
                            </div>
                            <div className="muted">
                              {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display} • status: {p.status}
                            </div>
                            {p.moderation_reason ? <div className="muted">Moderation reason: {p.moderation_reason}</div> : null}
                          </div>
                          <div className="spacer" />
                          <a href={url} target="_blank" rel="noreferrer">
                            Open ➜
                          </a>
                          <button
                            className="danger"
                            style={{ marginLeft: 10 }}
                            onClick={async () => {
                              const reason = window.prompt("Mark this post as SPAM? Reason (optional):", "SPAM") || "";
                              try {
                                await adminMarkSpam(pid, reason);
                                setMsg("Marked SPAM.");
                                await loadUser(activeUserId);
                              } catch (e: any) {
                                setMsg(e.message || "Spam action failed");
                              }
                            }}
                          >
                            Mark SPAM
                          </button>
                        </div>

                        {thumb ? (
                          <div className="post-media" style={{ marginTop: 10 }}>
                            {String(p.images[0]?.content_type || "").toLowerCase().startsWith("video/") ? (
                              <video controls preload="metadata" src={thumb} />
                            ) : (
                              <img src={thumb} alt={`Ad ${pid} media`} loading="lazy" />
                            )}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
                {!activePosts.length ? <div className="col-12 muted">No posts.</div> : null}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

