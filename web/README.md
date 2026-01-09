## Web app (same flow as mobile)

This folder contains the browser UI with the same core flow:

- Splash → Welcome → Login/Register → Home feed → Property detail → Subscription paywall → Profile
- Owner: create listing + upload photos
- Review/approve/reject pending listings (Admin link is hidden in UI)

### Optional UI assets

- **Home background image**: put your image at `web/public/home_bg.jpg`
  - Suggested content: **fabulous fully constructed building + interiors + gardens**
  - Suggested size: 1080×1920 or higher
  - If missing, the UI falls back to the glossy orange theme

### Run locally

```bash
cd web
npm install
npm run dev
```

Backend API base URL defaults to `http://127.0.0.1:8000`.
Override via `VITE_API_BASE_URL`.

