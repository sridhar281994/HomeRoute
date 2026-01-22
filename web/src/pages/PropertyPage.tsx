import { useEffect, useState } from "react";
import { getContact, getProperty, getSession, toApiUrl } from "../api";
import { Link, useNavigate, useParams } from "react-router-dom";
import { sharePost } from "../share";

export default function PropertyPage() {
  const { id } = useParams();
  const pid = Number(id);
  const pidOk = Number.isInteger(pid) && pid > 0;
  const [p, setP] = useState<any>(null);
  const [msg, setMsg] = useState("");
  const [contacted, setContacted] = useState(false);
  const nav = useNavigate();

  useEffect(() => {
    (async () => {
      setMsg("");
      if (!pidOk) {
        setP(null);
        setMsg("Invalid ad id.");
        return;
      }
      try {
        const data = await getProperty(pid);
        setP(data);
        setContacted(Boolean((data as any)?.contacted));
      } catch (e: any) {
        setMsg(e.message || "Failed");
      }
    })();
  }, [pid, pidOk]);

  if (!p) {
    return (
      <div className="panel">
        <div className="row">
          <p className="h1">Property</p>
          <div className="spacer" />
          <Link to="/home">Back</Link>
        </div>
        <p className="muted">{msg || "Loading..."}</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          {p.title}
        </p>
        <div className="spacer" />
        <button
          type="button"
          title="Share"
          aria-label="Share"
          onClick={async () => {
            const title = String(p.title || "Property").trim() || "Property";
            const adv = String(p.adv_number || p.advNo || p.id || "").trim();
            const meta = [
              adv ? `Ad #${adv}` : "",
              String(p.rent_sale || "").trim(),
              String(p.property_type || "").trim(),
              String(p.price_display || "").trim(),
              String(p.location_display || "").trim(),
            ]
              .filter(Boolean)
              .join(" • ");
            const url = pidOk ? `${window.location.origin}/property/${pid}` : window.location.href;
            const img = p.images?.length ? toApiUrl(p.images[0].url) : "";
            const text = [title, meta, img ? `Image: ${img}` : ""].filter(Boolean).join("\n");
            const res = await sharePost({ title, text, url });
            if (res === "copied") setMsg("Copied share text to clipboard.");
          }}
          style={{ padding: "8px 10px", minWidth: 44 }}
        >
          Share post
        </button>
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">
        Ad #{String(p.adv_number || p.advNo || p.id || "").trim()} • {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display}
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Photos</div>
            {p.images?.length ? (
              <div className="grid" style={{ marginTop: 10 }}>
                {p.images.map((i: any) => (
                  <div className="col-6" key={i.id ?? i.url}>
                    <a href={toApiUrl(i.url)} target="_blank" rel="noreferrer">
                      {String(i.content_type || "").toLowerCase().startsWith("video/") ? (
                        <video
                          controls
                          preload="metadata"
                          src={toApiUrl(i.url)}
                          style={{
                            width: "100%",
                            height: 220,
                            objectFit: "cover",
                            borderRadius: 14,
                            border: "1px solid rgba(255,255,255,.14)",
                            background: "rgba(0,0,0,.25)",
                          }}
                        />
                      ) : (
                        <img
                          src={toApiUrl(i.url)}
                          alt={`Property ${p.id} media`}
                          style={{
                            width: "100%",
                            height: 220,
                            objectFit: "cover",
                            borderRadius: 14,
                            border: "1px solid rgba(255,255,255,.14)",
                            background: "rgba(0,0,0,.25)",
                          }}
                          loading="lazy"
                        />
                      )}
                    </a>
                  </div>
                ))}
              </div>
            ) : (
              <div className="post-media placeholder" aria-hidden="true" style={{ marginTop: 10 }}>
                <div className="media-placeholder" />
                <div className="media-placeholder" />
                <div className="muted" style={{ gridColumn: "1 / -1", textAlign: "center" }}>
                  No Photos
                </div>
              </div>
            )}
          </div>
        </div>
        <div className="col-12">
          <div className="card">
            <div className="h2">Amenities</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {p.amenities?.length ? p.amenities.join(", ") : "—"}
            </div>
          </div>
        </div>
        <div className="col-12 row">
          <button
            className="primary"
            disabled={contacted}
            onClick={async () => {
              setMsg("");
              try {
                const s = getSession();
                if (!s.token) {
                  setMsg("Login required to contact owner.");
                  nav("/login");
                  return;
                }
                const contact = await getContact(pid);
                const ownerName = String(contact.owner_name || "").trim();
                const advNo = String(contact.adv_number || contact.advNo || "").trim();
                const sent = "Contact details sent to your registered email/SMS.";
                const header = advNo ? `Ad #${advNo}` : "Ad";
                const who = ownerName ? ` (${ownerName})` : "";
                setContacted(true);
                setMsg(`${sent} ${header}${who}.`);
              } catch (e: any) {
                setMsg(e.message || "Locked");
              }
            }}
          >
            {contacted ? "Contacted" : "Contact owner"}
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

