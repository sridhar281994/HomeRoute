import { useEffect, useState } from "react";
import { getContact, getProperty } from "../api";
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
          <Link to="/">Back</Link>
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
        <Link to="/">Back</Link>
      </div>
      <p className="muted">
        {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display}
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Photos</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {p.images?.length
                ? p.images.map((i: any) => i.url).join(" • ")
                : "No images yet (owner uploads via Owner screen)."}
            </div>
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
                setMsg(`Owner contact: ${contact.phone || "N/A"} / ${contact.email || "N/A"}`);
              } catch (e: any) {
                setMsg(e.message || "Locked");
              }
            }}
          >
            Unlock Contact
          </button>
          <Link to="/subscription">Subscription</Link>
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

