# Activity 5.1: saved full itineraries

The planner can explicitly save, list, load, update and permanently delete a complete itinerary with its original preferences. This uses a new `public.saved_itineraries` table, separate from legacy preference-only `public.trips`. Generation/refinement remain local until an explicit save or update. No migration or AI request runs automatically.

## Access and persistence

`supabase_clients.get_client()` verifies the user JWT through Supabase Auth, then forwards that JWT with a public publishable/anon key. Each request gets its own client and owner filters. Supabase RLS independently limits all four operations to `auth.uid() = user_id`. `get_service_client(explicit_admin=True)` is a separate server-only administrative entry point; authenticated saved-itinerary routes never call it or fall back to the legacy elevated store.

The API validates complete preference/itinerary snapshots on both writes and reads. History lists return summaries with bounded pagination, while detail requests return one validated snapshot. Saved status belongs to the persisted-record envelope; the generated-plan `saved: false` contract is preserved. The database trigger guards identity/ownership/creation timestamps and requires a one-step version increment. Updates and deletes condition on the expected version; conflicts retain the local editor contents.

| Endpoint | Behavior |
| --- | --- |
| `POST /api/saved-itineraries` | Create with a client UUID, title, preferences and itinerary |
| `GET /api/saved-itineraries?offset=0` | List up to 20 owned summaries |
| `GET /api/saved-itineraries/{id}` | Retrieve one owned full snapshot |
| `PUT /api/saved-itineraries/{id}` | Replace the snapshot with its expected `version` |
| `DELETE /api/saved-itineraries/{id}` | Permanently delete with JSON `{ "version": 1 }` |

All endpoints require a verified user session. Writes require JSON and a bounded body. Error responses do not expose database details. The UI distinguishes Save new from Update selected, confirms mutations, rejects stale load responses, and supports checking an uncertain create by its client UUID instead of blindly creating another copy. A confirmed 404 offers an explicit retry of the original snapshot with the same UUID; uncertain/auth/server failures do not unlock retry. Pending-save checks and retries preserve newer editor work and the current selection, including when the original request commits late. An initial allowlisted pre-storage validation rejection releases the pending operation so users can correct the plan and explicitly save again. A validation rejection during a retry of an uncertain operation does not release that original identity. Delete has no in-app recovery.

## Local setup

Review `ACTIVITY_5_1_APPROVAL.txt` and `migrations/002_saved_itineraries_REVIEW_ONLY.sql` before any database changes. The configured development project was manually migrated and verified; do not rerun that script there. Other projects must independently review and verify their setup.

Copy `.env.example` in this directory to `.env.local`, enter the project's existing public authentication key locally, and set the schema flag true only after verification. Do not copy credentials into chat, source control, logs, screenshots or frontend variables. The existing service configuration remains server-only and is not a user-CRUD fallback.

From the repository root on Windows:

```powershell
.\backend-python.venv\Scripts\python.exe -B -m uvicorn app.main:app --app-dir backend-python --env-file backend-python/.env.local --host 127.0.0.1 --port 5000
npm.cmd run dev --workspace=frontend
```

Run the two commands in separate terminals. Auth configuration is process-environment-only: the explicit `--env-file` flag is required for this file. Keep `APP_MODE=local` and `TRIP_OWNERSHIP_ENABLED=false`; this migration does not establish ownership for legacy preferences. Do not run Express on the same port.

## Verification and limits

The final source passed 539 Python tests, 312 JavaScript tests (27 shared, 204 frontend, 81 legacy backend) and the Vite production build. Unit/integration tests use mocks rather than real credentials. Additional authorized live tests used two synthetic QA accounts: both created, listed, retrieved and updated their own records; stale writes failed; cross-account read/edit/delete failed through both the API and direct RLS; unauthenticated access failed. Seven existing preference records matched their pre-test fingerprint.

User-assisted browser testing verified load, edit/update, delete confirmation and Cancel, followed by separately authorized owner deletion. The backend logged one successful deletion for that synthetic record and a read-only database check confirmed it absent. Another QA record and both QA accounts were retained. Private identifiers, account credentials, exports and audit logs are intentionally excluded from this repository.

Browser Save new also passed through a user-operated confirmation: an independent database read verified a new UUID, revision 1, the expected owner, and the complete validated snapshot. The previously deleted record remained absent; the other QA record, both accounts, and legacy preferences were unchanged. Browser actions were performed by the user because the signed-in browser was not accessible to automation; database/API checks provide independent supporting evidence. Do not describe API-only checks as browser tests.

This remains a trusted-operator local prototype. Legacy preference history is project-wide in local mode, while the new full-itinerary table is account-scoped. Public deployment, production security hardening, shared/group collaboration, automatic AI persistence and SkillWallet progress submission are not included. Authentication sessions stay in memory and end on refresh or expiry. Existing Epics 3/4 behavior and refinement-only Groq model routing are preserved.
