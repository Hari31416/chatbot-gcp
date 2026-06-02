# Phase 8 — Firebase Hosting Migration

> Replace Azure Static Web Apps with Firebase Hosting for the Vite SPA.

---

## Goal

Deploy the React build output to Firebase Hosting with SPA fallback routing and environment-specific Firebase Auth configuration.

---

## Current State (Azure)

| File                                | Role                                   |
| :---------------------------------- | :------------------------------------- |
| `frontend/staticwebapp.config.json` | Azure SWA fallback routing and headers |
| `deploy-frontend.sh`                | Azure SWA deployment                   |
| `frontend/.env`                     | API and auth configuration             |

---

## Target State

### 8.1 Add Hosting Configuration

Create `frontend/firebase.json`:

```json
{
  "hosting": {
    "public": "dist",
    "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
    "rewrites": [{ "source": "**", "destination": "/index.html" }],
    "headers": [
      {
        "source": "**/*.@(js|css)",
        "headers": [
          {
            "key": "Cache-Control",
            "value": "public,max-age=31536000,immutable"
          }
        ]
      }
    ]
  }
}
```

Create `frontend/.firebaserc.example`:

```json
{
  "projects": {
    "default": "replace-with-project-id"
  }
}
```

### 8.2 Update Environment Variables

Create `frontend/.env.example`:

```bash
VITE_API_BASE_URL=https://<cloud-run-chatbot-api-url>
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=<project-id>.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=
VITE_FIREBASE_APP_ID=
VITE_FIREBASE_AUTH_EMULATOR_URL=
```

### 8.3 Replace the Deploy Script

Update `deploy-frontend.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd frontend
pnpm install --frozen-lockfile
pnpm build
firebase deploy --only hosting --project "${GCP_PROJECT_ID:?GCP_PROJECT_ID is required}"
```

Keep `frontend/staticwebapp.config.json` until Phase 10 so the Azure frontend remains redeployable.

---

## Deployment

```bash
cd frontend
pnpm build
firebase deploy --only hosting --project "$GCP_PROJECT_ID"
```

---

## Local Development

```bash
cd frontend
pnpm dev

# Or validate built SPA fallback behavior:
pnpm build
firebase emulators:start --only hosting
```

---

## Cost Control

Firebase Hosting has no-cost storage and transfer quotas suitable for a small PoC. Set usage alerts and avoid storing uploaded user documents in Hosting; those belong in GCS.

Reference: [Firebase Hosting quotas and pricing](https://firebase.google.com/docs/hosting/usage-quotas-pricing)

---

## Verification

- [ ] `pnpm build` passes.
- [ ] Firebase Hosting serves the SPA over HTTPS.
- [ ] Refreshing a nested SPA route returns `index.html`.
- [ ] Sign-in and authenticated API calls work from the Hosting origin.
- [ ] Static assets receive long-lived cache headers.

---

## Next Phase

→ [Phase 9 — Observability & Budgets](./PHASE_9_OBSERVABILITY.md)
