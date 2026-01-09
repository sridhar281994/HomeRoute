import { useEffect, useState } from "react";
import { getSession, ownerCreateProperty, uploadPropertyImage } from "../api";
import { Link, useNavigate } from "react-router-dom";

export default function OwnerAddPage() {
  const nav = useNavigate();
  const s = getSession();
  const [title, setTitle] = useState("");
  const [location, setLocation] = useState("");
  const [price, setPrice] = useState("");
  const [rentSale, setRentSale] = useState("rent");
  const [propertyType, setPropertyType] = useState("apartment");
  const [contactPhone, setContactPhone] = useState("");
  const [contactEmail, setContactEmail] = useState("");
  const [propertyId, setPropertyId] = useState<number | null>(null);
  const [msg, setMsg] = useState("");
  const [files, setFiles] = useState<FileList | null>(null);

  useEffect(() => {
    if (!s.token) nav("/login");
  }, [nav, s.token]);

  if ((s.user?.role || "").toLowerCase() !== "owner") {
    return (
      <div className="panel">
        <p className="h1">Owner Dashboard  🏢</p>
        <p className="muted">Owner access only. Please login/register as an Owner account.</p>
        <Link to="/home">Back</Link>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="row">
        <p className="h1" style={{ margin: 0 }}>
          Owner: Add Listing  ➕
        </p>
        <div className="spacer" />
        <Link to="/home">Back</Link>
      </div>
      <p className="muted">
        Create the listing first, then upload photos (plot/rent/floor accessories/etc).
      </p>

      <div className="grid" style={{ marginTop: 12 }}>
        <div className="col-6">
          <label className="muted">Title</label>
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Location</label>
          <input value={location} onChange={(e) => setLocation(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Price</label>
          <input value={price} onChange={(e) => setPrice(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Rent/Sale</label>
          <select value={rentSale} onChange={(e) => setRentSale(e.target.value)}>
            <option value="rent">rent</option>
            <option value="sale">sale</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Type</label>
          <select value={propertyType} onChange={(e) => setPropertyType(e.target.value)}>
            <option value="apartment">apartment</option>
            <option value="house">house</option>
            <option value="villa">villa</option>
            <option value="studio">studio</option>
            <option value="land">land</option>
          </select>
        </div>
        <div className="col-6">
          <label className="muted">Contact phone</label>
          <input value={contactPhone} onChange={(e) => setContactPhone(e.target.value)} />
        </div>
        <div className="col-6">
          <label className="muted">Contact email</label>
          <input value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
        </div>

        <div className="col-12 row">
          <button
            className="primary"
            onClick={async () => {
              setMsg("");
              try {
                const res = await ownerCreateProperty({
                  title,
                  location,
                  price: Number(price || 0),
                  rent_sale: rentSale,
                  property_type: propertyType,
                  contact_phone: contactPhone,
                  contact_email: contactEmail,
                  amenities: [],
                });
                setPropertyId(res.id);
                setMsg(`Created listing #${res.id} (status: ${res.status}). Upload photos below.`);
              } catch (e: any) {
                setMsg(e.message || "Failed");
              }
            }}
          >
            Submit listing (goes to admin review)
          </button>
          <span className="muted">{msg}</span>
        </div>

        <div className="col-12">
          <div className="card">
            <div className="h2">Upload photos</div>
            <p className="muted" style={{ marginTop: 6 }}>
              Supports multiple images. Stored on server under <code>/uploads</code>.
            </p>
            <input
              type="file"
              multiple
              accept="image/*"
              onChange={(e) => setFiles(e.target.files)}
            />
            <div className="row" style={{ marginTop: 10 }}>
              <button
                onClick={async () => {
                  if (!propertyId) return setMsg("Create the listing first.");
                  if (!files?.length) return setMsg("Choose at least one image.");
                  try {
                    for (let i = 0; i < files.length; i++) {
                      await uploadPropertyImage(propertyId, files[i], i);
                    }
                    setMsg(`Uploaded ${files.length} image(s) to listing #${propertyId}.`);
                  } catch (e: any) {
                    setMsg(e.message || "Upload failed");
                  }
                }}
              >
                Upload
              </button>
              <span className="muted">
                {propertyId ? `Listing: #${propertyId}` : "Listing: (not created yet)"}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

