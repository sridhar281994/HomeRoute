import { useEffect, useState } from "react";
import { getContact, getProperty, getSession } from "../api";
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
        {p.rent_sale} • {p.property_type} • {p.price_display} • {p.location_display}
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-12">
          <div className="card">
            <div className="h2">Photos</div>
            <div className="muted" style={{ marginTop: 6 }}>
              {p.images?.length
                ? p.images.map((i: any) => i.url).join(" • ")
                : "No images yet (owner uploads via Publish Ad screen)."}
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
                const phone = String(contact.phone || "").trim();
                const email = String(contact.email || "").trim();
                const ownerName = String(contact.owner_name || "").trim();
                const advNo = String(contact.adv_number || contact.advNo || "").trim();
                const header = advNo ? `Ad #${advNo}` : "Ad";
                const who = ownerName ? ` (${ownerName})` : "";
                if (phone && email) setMsg(`${header}${who} contact: ${phone} / ${email}`);
                else if (phone) setMsg(`${header}${who} contact: ${phone}`);
                else if (email) setMsg(`${header}${who} contact: ${email}`);
                else setMsg("Owner contact: N/A");
              } catch (e: any) {
                setMsg(e.message || "Locked");
              }
            }}
          >
            Unlock Contact  🔓
          </button>
          {getSession().token ? <Link to="/subscription">Subscription</Link> : <Link to="/login">Login</Link>}
          <span className="muted">{msg}</span>
        </div>
      </div>
    </div>
  );
}

