# Phase 4 — Authentication Migration

> Replace Amazon Cognito User Pools with Microsoft Entra External ID on both backend (JWT validation) and frontend (auth flows).

---

## Goal

Swap the entire authentication layer — user sign-up, sign-in, JWT token issuance, and token verification — from AWS Cognito to Microsoft Entra External ID. This requires changes to both the frontend (`auth.ts`, `AuthGate.tsx`) and backend (`dependencies.py`).

---

## Current State (AWS)

### Frontend (`frontend/src/services/auth.ts`)

- Direct REST calls to `https://cognito-idp.{region}.amazonaws.com/`
- Uses `X-Amz-Target` headers for `SignUp`, `ConfirmSignUp`, `InitiateAuth`
- Stores `idToken`, `accessToken`, `refreshToken` in `localStorage`
- Env vars: `VITE_COGNITO_CLIENT_ID`, `VITE_AWS_REGION`

### Backend (`backend/app/dependencies.py`)

- `get_current_user_id()` extracts user from:
  1. AWS Lambda event context (`aws.event.requestContext.authorizer.jwt.claims`)
  2. Bearer token → JWKS verification against Cognito JWKS URL
  3. Fallback headers / dev mode
- JWKS URL: `https://cognito-idp.{region}.amazonaws.com/{pool_id}/.well-known/jwks.json`
- Settings: `cognito_user_pool_id`, `cognito_client_id`

---

## Target State (Azure)

### Microsoft Entra External ID

- **Free tier:** 50,000 MAU (vs Cognito's 10,000)
- **Token format:** Standard OIDC JWT (RS256), verified via Microsoft JWKS
- **Frontend SDK:** MSAL.js v2 (`@azure/msal-browser`)
- **Backend verification:** Standard JWKS endpoint at `https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys`

---

## Code Changes

### 4.1 Frontend — Install MSAL.js

```bash
cd frontend
pnpm add @azure/msal-browser
```

### 4.2 Frontend — Rewrite `src/services/auth.ts`

Replace Cognito REST calls with MSAL.js:

```typescript
import {
  PublicClientApplication,
  type AuthenticationResult,
  type AccountInfo,
} from "@azure/msal-browser";

const msalConfig = {
  auth: {
    clientId: import.meta.env.VITE_AZURE_CLIENT_ID || "",
    authority: import.meta.env.VITE_ENTRA_AUTHORITY || "",
    redirectUri: window.location.origin,
  },
  cache: {
    cacheLocation: "localStorage" as const,
    storeAuthStateInCookie: false,
  },
};

const loginRequest = {
  scopes: ["openid", "profile", "email"],
};

let msalInstance: PublicClientApplication | null = null;

async function getMsalInstance(): Promise<PublicClientApplication> {
  if (!msalInstance) {
    msalInstance = new PublicClientApplication(msalConfig);
    await msalInstance.initialize();
  }
  return msalInstance;
}

export interface AuthSession {
  accessToken: string;
  idToken: string;
  email: string;
}

export async function signUpUser(
  email: string,
  password: string,
): Promise<string> {
  // Entra External ID handles sign-up via redirect flow
  // For email/password sign-up, use the sign-up authority
  const instance = await getMsalInstance();
  await instance.loginPopup({
    ...loginRequest,
    authority: `${msalConfig.auth.authority}/signup`,
    loginHint: email,
  });
  return email;
}

export async function signInUser(
  email: string,
  password: string,
): Promise<AuthSession> {
  const instance = await getMsalInstance();
  const result: AuthenticationResult = await instance.loginPopup({
    ...loginRequest,
    loginHint: email,
  });

  return {
    accessToken: result.accessToken,
    idToken: result.idToken || "",
    email: result.account?.username || email,
  };
}

export function signOutUser(): void {
  if (msalInstance) {
    msalInstance.logoutPopup();
  }
  localStorage.removeItem("auth_id_token");
  localStorage.removeItem("auth_access_token");
  localStorage.removeItem("auth_user_email");
}

export function isUserLoggedIn(): boolean {
  if (!msalInstance) return !!localStorage.getItem("auth_id_token");
  const accounts = msalInstance.getAllAccounts();
  return accounts.length > 0;
}

export function getCurrentUserEmail(): string {
  if (msalInstance) {
    const accounts = msalInstance.getAllAccounts();
    if (accounts.length > 0) return accounts[0].username;
  }
  return localStorage.getItem("auth_user_email") || "Guest";
}

export async function getCurrentSessionToken(): Promise<string | null> {
  if (!msalInstance) return localStorage.getItem("auth_id_token");
  const accounts = msalInstance.getAllAccounts();
  if (accounts.length === 0) return null;

  try {
    const result = await msalInstance.acquireTokenSilent({
      ...loginRequest,
      account: accounts[0],
    });
    return result.idToken || result.accessToken;
  } catch {
    return null;
  }
}
```

> [!WARNING]
> `getCurrentSessionToken()` becomes **async** in the MSAL version (token refresh is async). All callers in `api.ts` and `App.tsx` must be updated to `await` the token retrieval.

### 4.3 Frontend — Update `src/services/api.ts`

All API calls that use `getCurrentSessionToken()` must be updated:

```diff
- const token = getCurrentSessionToken()
+ const token = await getCurrentSessionToken()
```

### 4.4 Frontend — Update `src/components/AuthGate.tsx`

- Replace `signUpUser` / `confirmSignUpUser` / `signInUser` imports with new MSAL versions
- Remove the "Confirm Sign-Up" (verification code) step — Entra handles email verification in its hosted UI
- Update the sign-in flow to use `loginPopup` instead of direct REST

### 4.5 Frontend — Update Environment Variables

```diff
- VITE_COGNITO_CLIENT_ID=...
- VITE_COGNITO_USER_POOL_ID=...
- VITE_AWS_REGION=...
+ VITE_AZURE_CLIENT_ID=your-entra-app-client-id
+ VITE_ENTRA_AUTHORITY=https://your-tenant.ciamlogin.com
```

### 4.6 Backend — Update `app/settings.py`

```diff
- cognito_user_pool_id: str | None = ...
- cognito_client_id: str | None = ...
+ azure_tenant_id: str | None = Field(default=None, validation_alias="AZURE_TENANT_ID")
+ azure_client_id: str | None = Field(default=None, validation_alias="AZURE_CLIENT_ID")
+ entra_authority: str | None = Field(default=None, validation_alias="ENTRA_AUTHORITY")
```

### 4.7 Backend — Rewrite `get_current_user_id()` in `dependencies.py`

Replace Cognito JWKS validation with Entra JWKS validation:

```python
def get_current_user_id(request: Request, settings: Settings = Depends(get_settings)) -> str:
    # 1. Extract Bearer token
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

        # Local dev: short dummy tokens
        if token and (len(token) < 50 or token.count(".") != 2):
            if settings.azure_tenant_id:
                raise HTTPException(status_code=401, detail="Invalid token format")
            return token

        # Verify JWT against Entra JWKS
        if settings.azure_tenant_id:
            try:
                import jwt
                unverified_header = jwt.get_unverified_header(token)
                kid = unverified_header.get("kid")

                # Entra JWKS endpoint
                jwks_url = f"https://login.microsoftonline.com/{settings.azure_tenant_id}/discovery/v2.0/keys"
                jwks = get_jwks(jwks_url)

                public_key = None
                for key in jwks.get("keys", []):
                    if key.get("kid") == kid:
                        from jwt.algorithms import RSAAlgorithm
                        public_key = RSAAlgorithm.from_jwk(key)
                        break

                if public_key:
                    payload = jwt.decode(
                        token,
                        public_key,
                        algorithms=["RS256"],
                        audience=settings.azure_client_id,
                        options={"verify_exp": True},
                    )
                    return _first_string_claim(payload, ("sub", "email", "preferred_username", "oid"))

                raise HTTPException(status_code=401, detail="Token key ID not found in Entra JWKS")
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("JWT validation failed: %s", e)
                raise HTTPException(status_code=401, detail=f"Signature verification failed: {e}")

        # Dev fallback: unverified decode
        try:
            import jwt
            payload = jwt.decode(token, options={"verify_signature": False})
            return _first_string_claim(payload, ("sub", "email", "preferred_username"), default="admin")
        except Exception:
            return "admin"

    # 2. Custom local headers
    x_user = request.headers.get("X-User-ID")
    if x_user:
        return x_user

    # 3. Strict auth in production
    if settings.azure_tenant_id:
        raise HTTPException(status_code=401, detail="Authorization header is required")

    return "admin"
```

### 4.8 Backend — Remove AWS Lambda Event Extraction

In the rewritten `get_current_user_id()`, the AWS Lambda `aws.event` extraction (lines 202-212 of the original) is removed since Azure Container Apps does not inject claims via scope context.

---

## Entra External ID Setup (Azure Portal / CLI)

This requires manual Azure portal steps:

1. **Create an External ID tenant** at [entra.microsoft.com](https://entra.microsoft.com)
2. **Register an application** → get `clientId`
3. **Configure redirect URIs**: `http://localhost:3333` (dev), `https://your-domain.com` (prod)
4. **Enable user flows**: Email sign-up/sign-in
5. **Note the authority URL**: `https://{tenant-name}.ciamlogin.com`

> [!IMPORTANT]
> Entra External ID tenant creation is a one-time manual step. It cannot be fully automated via Bicep (the tenant itself is created in the Azure portal, though app registrations can be scripted via Microsoft Graph API).

---

## Verification

- [ ] Frontend sign-up flow opens Entra hosted UI
- [ ] Frontend sign-in returns valid `idToken` and `accessToken`
- [ ] `getCurrentSessionToken()` returns a valid token (or refreshes silently)
- [ ] Backend validates Entra JWT using JWKS endpoint
- [ ] Backend extracts `sub` / `email` / `preferred_username` from token claims
- [ ] Dev mode fallback (`X-User-ID` header) still works when `AZURE_TENANT_ID` is unset
- [ ] `pnpm build` succeeds with no type errors

---

## Next Phase

→ [Phase 5 — Event-Driven Ingestion](./PHASE_5_INGESTION.md)
