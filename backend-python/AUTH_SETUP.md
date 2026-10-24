# Authentication and ownership setup (not yet live-verified)

The backend implements Supabase email/password registration, login, and bearer verification. It does not mint test JWTs or trust decoded user JWT claims. Each protected request calls Supabase Auth `GET /auth/v1/user`. Registration without a session returns `pending_confirmation: true`, not a claim that an account was created or email confirmed.

## Configuration

Set backend process environment only (not frontend Vite variables):

- `SUPABASE_URL=https://YOUR_PROJECT.supabase.co`
- `SUPABASE_PUBLISHABLE_KEY=...` (or legacy `SUPABASE_ANON_KEY`; never a service-role/secret key for auth/owned access)
- `APP_MODE=local` by default. Local legacy trips remain single-user, unowned, loopback-only—not authenticated or safe to publish.

Auth currently reads environment variables only; the local privileged trip adapter's separate `.env` behavior does not configure Auth automatically. No credentials were read or configured as part of implementation.

For an eventual approved deployment, the owner-scoped adapter must be integrated and verified, `TRIP_OWNERSHIP_ENABLED=true` and `TRIP_OWNERSHIP_SCHEMA_VERIFIED=true` must be set, along with `APP_MODE=production`. The flags do not migrate or prove the database schema. Missing configuration or missing adapter support returns 503 instead of exposing privileged legacy trips. Exact HTTPS CORS frontend origin and deployment setup are documented separately by integration.

## Database approval is still required

`migrations/001_trip_ownership_REVIEW_ONLY.sql` is a draft, **not applied**. It adds nullable `user_id`, owner RLS, and denies anonymous table access. Review existing policies/grants/views/triggers and backup first. All existing rows remain NULL/unowned; their ownership requires an explicit approved decision, never automatic assignment. Test two-user isolation, null-row invisibility, and insert/update/delete protections before declaring the schema verified. Public deployment and actual DDL were not authorized or attempted.

## Browser/session contract

`POST /api/auth/register` and `/api/auth/login` accept `{email,password}`. Response contains `{user,session,pending_confirmation}`. Session contains the provider access token, bearer type, expires_in and computed expires_at, but no refresh token. Keep tokens only in memory, never localStorage, logs, URLs, or preferences. On expiry/401 or logout clear sensitive state and sign in again. `POST /api/auth/logout` with bearer revokes the current refresh session; already-issued access JWTs may remain valid until expiry. This is not an immediate token-revocation guarantee.

Both registration and login enforce valid email shape and 8–128 character passwords. Configure Supabase password policy, email confirmations, redirect allowlist, delivery/SMTP, abuse controls, and rate limits before public use. This implementation has no password-reset/refresh workflow and does not claim one.

## Verification scope

Automated tests use only synthetic configuration + httpx.MockTransport; no real login, email, account creation, table reads/writes, or migration. Live auth and RLS setup remain unverified.

Official references inspected 2026-10-24:

- https://supabase.github.io/auth/ — Auth REST signup, password token, user and logout endpoints.
- https://supabase.com/docs/reference/javascript/auth-getuser — server-validated user retrieval.
- https://supabase.com/docs/reference/javascript/auth-signup — confirmation/session and existing-user behavior.
