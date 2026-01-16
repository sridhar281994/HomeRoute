import { useEffect, useState } from "react";
import { getContact, getProperty, getSession, toApiUrl } from "../api";
import { Link, useParams } from "react-router-dom";

export default function PropertyPage() {
  const { id } = useParams();
  const pid = Number(id);
  const [p, setP] = useState<any>(null);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    (async () => {
      setMsg("");
      try {
        const data = await getProperty(pid);
        setP(data);
      } catch (e: any) {
        setMsg(e.message || "Failed");
      }
    })();
  }, [pid]);

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
              <div className="muted" style={{ marginTop: 6 }}>
                Photos will appear once uploaded.
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
            onClick={async () => {
              setMsg("");
              try {
                const contact = await getContact(pid);
                const ownerName = String(contact.owner_name || "").trim();
                const advNo = String(contact.adv_number || contact.advNo || "").trim();
                const sent = "Contact details sent to your registered email/SMS.";
                const header = advNo ? `Ad #${advNo}` : "Ad";
                const who = ownerName ? ` (${ownerName})` : "";
                setMsg(`${sent} ${header}${who}.`);
              } catch (e: any) {
                setMsg(e.message || "Locked");
              }
            }}
          >
            Contact owner
          </button>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

