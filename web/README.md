## Web app (same flow as mobile)

This folder contains the browser UI with the same core flow:

- Splash → Welcome → Login/Register → Home feed → Property detail → Subscription paywall → Profile
- Owner: create listing + upload photos
- Admin: review/approve/reject pending listings

### Run locally

```bash
cd web
npm install
npm run dev
```

Backend API base URL defaults to `http://127.0.0.1:8000`.
Override via `VITE_API_BASE_URL`.

