# Clerk Authentication Setup

This app uses [Clerk](https://clerk.com) for sign-in/sign-up. The React SPA obtains session JWTs; the FastAPI Container App validates them via Clerk's JWKS endpoint. The ingestion Function App does not use Clerk.

## How to find the Frontend API URL (`CLERK_ISSUER`)

This value is **required** for backend JWT validation. It is **not** the same as the publishable or secret key.

1. Open **[Clerk Dashboard](https://dashboard.clerk.com)** and select your application.
2. Go to **Configure** → **Developers** → **[API keys](https://dashboard.clerk.com/last-active?path=api-keys)**.
3. On that page, find **Frontend API** (sometimes labeled **Frontend API URL**).
   - Example: `https://clever-crane-12.clerk.accounts.dev`
4. Set it in your root `.env` as:

   ```env
   CLERK_ISSUER=https://clever-crane-12.clerk.accounts.dev
   ```

**Tips**

- Use the full URL including `https://`. Do not add a trailing path.
- JWKS is derived automatically: `{CLERK_ISSUER}/.well-known/jwks.json`
- If you use a **custom Clerk domain**, use that hostname as the issuer (same place in the dashboard).
- The publishable key (`pk_test_…`) is paired with this instance; both come from the same app in the dashboard.

## Keys overview

| Variable                     | Clerk Dashboard      | Where to set                    | Secret?           |
| ---------------------------- | -------------------- | ------------------------------- | ----------------- |
| `VITE_CLERK_PUBLISHABLE_KEY` | Publishable key      | `frontend/.env` only            | No (browser-safe) |
| `CLERK_ISSUER`               | **Frontend API URL** | Root `.env` + Container App env | No                |
| `CLERK_AUTHORIZED_PARTIES`   | Your app origins     | Root `.env` + Container App     | No                |
| `CLERK_SECRET_KEY`           | Secret key           | **Azure Key Vault** (see below) | **Yes**           |

> **Important:** JWT login for this app works with `CLERK_ISSUER` + JWKS. The secret key is **not** used for validating browser session tokens. Store it in Key Vault for future Clerk Backend API calls or rotation workflows.

## Where each file lives

| File            | Purpose                                                           |
| --------------- | ----------------------------------------------------------------- |
| `frontend/.env` | `VITE_CLERK_PUBLISHABLE_KEY`, `VITE_API_BASE_URL`                 |
| Root `.env`     | `CLERK_ISSUER`, `CLERK_AUTHORIZED_PARTIES`, `AZURE_KEYVAULT_NAME` |
| Azure Key Vault | `clerk-secret-key` (never commit)                                 |

Do **not** put `VITE_*` variables only in the root `.env` — Vite reads `frontend/.env` by default.

## Store `CLERK_SECRET_KEY` in Azure Key Vault

This project uses **Azure Key Vault** (not macOS Keychain) for server secrets, consistent with LiteLLM and Cosmos keys.

### One-time: upload the secret

```bash
# From repo root; use your vault name from AZURE_KEYVAULT_NAME or deployment outputs
az keyvault secret set \
  --vault-name "kv-chatbot-YOUR_TOKEN" \
  --name "clerk-secret-key" \
  --value "$CLERK_SECRET_KEY"
```

Or provision on deploy (secret read from local `.env` once, then **remove from `.env`**):

```bash
# .env contains CLERK_SECRET_KEY only for this command
make deploy-infra
```

### Runtime resolution (backend)

The backend resolves secrets in this order:

1. Key Vault secret `clerk-secret-key` (when `AZURE_KEYVAULT_NAME` is set and you are logged in / managed identity on Azure)
2. Fallback: `CLERK_SECRET_KEY` in `.env` (local dev only)

Code: `get_clerk_secret_key()` in `backend/app/dependencies.py`.

### Local dev with Key Vault

```env
AZURE_KEYVAULT_NAME=kv-chatbot-xxxx
CLERK_ISSUER=https://your-instance.clerk.accounts.dev
CLERK_AUTHORIZED_PARTIES=http://localhost:3000
```

```bash
az login
# Your user needs Key Vault Secrets User on the vault
cd backend && uv run uvicorn app.main:app --reload --port 8080
```

Remove `CLERK_SECRET_KEY` from `.env` after it is in Key Vault.

## Azure deployment commands

**Container App** — from root `.env` via `make deploy-infra` or `make deploy-backend`:

- `CLERK_ISSUER`
- `CLERK_AUTHORIZED_PARTIES`

**Static Web App** — `frontend/.env` at build time:

- `VITE_CLERK_PUBLISHABLE_KEY`
- `VITE_API_BASE_URL`

```bash
make deploy-backend      # API image + Clerk env on Container App
make deploy-functions    # ingestion worker (queue trigger)
make deploy-frontend     # Vite build → SWA
```

## `CLERK_AUTHORIZED_PARTIES`

Comma-separated origins that must match the JWT `azp` claim:

```env
CLERK_AUTHORIZED_PARTIES=http://localhost:3000,https://your-swa.azurestaticapps.net
```

## Clerk Dashboard checklist

1. **API keys**: Copy publishable key + Frontend API URL + secret key.
2. **Paths / URLs**: Add `http://localhost:3000` and production frontend URL under allowed redirect URLs.
3. Default session tokens are sufficient (no custom JWT template).

## Verify

1. `frontend/.env` has `VITE_CLERK_PUBLISHABLE_KEY`.
2. Root `.env` has `CLERK_ISSUER` and `CLERK_AUTHORIZED_PARTIES`.
3. Start backend and frontend; sign in; API calls return 200 with `Authorization: Bearer …`.
4. User id in Cosmos is Clerk `sub` (e.g. `user_2abc…`).
