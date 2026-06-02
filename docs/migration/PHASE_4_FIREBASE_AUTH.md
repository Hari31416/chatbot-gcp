# Phase 4 — Firebase Authentication Migration

> Replace Clerk frontend sessions and Clerk JWKS validation with Firebase Authentication and Firebase Admin token verification.

---

## Goal

Use Firebase Authentication email/password sign-in for the PoC. The SPA obtains Firebase ID tokens; FastAPI verifies them with the Firebase Admin SDK.

---

## Current State (Azure Deployment)

| File                                        | Clerk Dependency                           |
| :------------------------------------------ | :----------------------------------------- |
| `frontend/package.json`                     | `@clerk/react`                             |
| `frontend/src/main.tsx`                     | Clerk provider                             |
| `frontend/src/services/auth.ts`             | Clerk token getter bridge                  |
| `frontend/src/components/AuthGate.tsx`      | Clerk sign-in and session UI               |
| `frontend/src/components/ClerkAuthSync.tsx` | Clerk-specific token synchronization       |
| `backend/app/dependencies.py`               | Clerk issuer, JWKS cache, JWT verification |
| `backend/app/settings.py`                   | Clerk issuer and authorized parties        |

---

## Target State

```txt
React SPA ── signInWithEmailAndPassword() ──► Firebase Authentication
React SPA ◄──────────── Firebase ID token ───┘
React SPA ───── Authorization: Bearer <ID token> ─────► FastAPI
FastAPI ───────── firebase_admin.auth.verify_id_token() ─────────► verified uid
```

---

## Frontend Changes

### 4.1 Replace Dependencies

```bash
cd frontend
pnpm remove @clerk/react
pnpm add firebase
```

### 4.2 Add Firebase Initialization

Create `frontend/src/services/firebase.ts`:

```typescript
import { getApps, initializeApp } from "firebase/app";
import { connectAuthEmulator, getAuth } from "firebase/auth";

const app =
  getApps()[0] ??
  initializeApp({
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
    appId: import.meta.env.VITE_FIREBASE_APP_ID,
  });

export const auth = getAuth(app);

if (import.meta.env.DEV && import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_URL) {
  connectAuthEmulator(auth, import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_URL);
}
```

### 4.3 Replace the Token Bridge

Rewrite `frontend/src/services/auth.ts`:

```typescript
import { auth } from "./firebase";

export async function getCurrentSessionToken(): Promise<string | null> {
  return auth.currentUser?.getIdToken() ?? null;
}
```

### 4.4 Rewrite `AuthGate`

Use Firebase Auth primitives:

```typescript
createUserWithEmailAndPassword(auth, email, password);
signInWithEmailAndPassword(auth, email, password);
signOut(auth);
onAuthStateChanged(auth, callback);
```

Delete `frontend/src/components/ClerkAuthSync.tsx` after all callers are removed.

### 4.5 Add Frontend Environment Variables

```bash
VITE_FIREBASE_API_KEY=
VITE_FIREBASE_AUTH_DOMAIN=<project-id>.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=
VITE_FIREBASE_APP_ID=
VITE_FIREBASE_AUTH_EMULATOR_URL=
```

Firebase web app configuration is public configuration, not a server secret. Still keep environment-specific values out of committed production files.

---

## Backend Changes

### 4.6 Add Firebase Admin

Update `backend/pyproject.toml`:

```diff
+  "firebase-admin>=6.6.0",
```

### 4.7 Replace Clerk Validation

In `backend/app/dependencies.py`, remove Clerk JWKS caching, unverified decode logic, and Clerk secret lookup. Add:

```python
import firebase_admin
from firebase_admin import auth


def _ensure_firebase_app() -> None:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def get_current_user_id(request: Request) -> str:
    token = _extract_bearer_token(request)
    _ensure_firebase_app()
    try:
        decoded = auth.verify_id_token(token)
    except Exception as exc:
        logger.warning("Firebase token verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid authentication token") from exc
    return str(decoded["uid"])
```

Use ADC locally and Cloud Run service-account identity in GCP. Do not ship a Firebase Admin private-key JSON file.

### 4.8 Replace Settings

Remove Clerk settings from `backend/app/settings.py`. Add:

```python
firebase_project_id: str | None = Field(default=None, validation_alias="FIREBASE_PROJECT_ID")
firebase_auth_emulator_host: str | None = Field(
    default=None,
    validation_alias="FIREBASE_AUTH_EMULATOR_HOST",
)
```

---

## Firebase Console Setup

1. Open Firebase Console → Authentication → Sign-in method.
2. Enable Email/Password.
3. Register a Web App.
4. Copy web configuration values into the frontend deployment environment.
5. Add Firebase Hosting domains and local development origins as authorized domains.

---

## Local Development

```bash
firebase init emulators
firebase emulators:start --only auth
export FIREBASE_AUTH_EMULATOR_HOST=127.0.0.1:9099
```

---

## Verification

- [ ] User can register, sign in, sign out, and refresh the page.
- [ ] Frontend sends a Firebase ID token on protected requests.
- [ ] Backend rejects missing, expired, malformed, and wrong-project tokens.
- [ ] Backend uses Firebase `uid` as the stable user ID.
- [ ] `rg -n "Clerk|clerk|@clerk" backend frontend` returns no active code references.

---

## Next Phase

→ [Phase 5 — Event-Driven Ingestion](./PHASE_5_INGESTION.md)
