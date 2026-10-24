# Activity 3.1 checkpoint — preference capture

## Status

- The uploaded sanitized project was copied into a separate working folder before edits. The original folder and ZIP are not changed.
- Form defaults and validation are implemented and tested first.
- Submission wiring and the Supabase adapter use the confirmed existing table. Automated tests inject fake storage; the real client initializes only when a configured save is attempted.
- **Real Supabase end-to-end verification remains pending. Activity 3.1 is not complete until a local save and stored values are confirmed.**
- No new table, migration, Git repository, GitHub push, authentication flow, or deployment is part of this checkpoint.

## Form and public API contract

`POST /api/trips` accepts JSON with exactly these fields. These are **API field names**, not assumptions about existing database columns.

| Field | Accepted value |
| --- | --- |
| `destination`, `departureCity` | Nonempty strings, trimmed, at most 200 characters, no control characters |
| `startDate`, `endDate` | Real `YYYY-MM-DD` calendar dates; end date on/after start date |
| `travelers` | Integer from 1 through 20 |
| `budget` | Finite number greater than zero |
| `currency` | `USD`, `EUR`, `INR` |
| `interests` | Array of unique IDs: `culture`, `food`, `adventure`, `nature`, `nightlife`, `shopping`, `relaxation`, `history`; empty is allowed |
| `dietaryNeeds` | `""` (no preference), `vegetarian`, `vegan`, `jain`, `halal` |
| `travelPace` | `relaxed`, `balanced`, `fast` |

All fields are required in the JSON request. The form initializes `dietaryNeeds` to `""` and `travelPace` to `balanced`; it converts number-input strings into actual JSON numbers before validation. The server independently validates the same shared contract without coercing arbitrary types. Unknown fields, nested objects, impossible dates, duplicate interests, and invalid enum values are rejected.

A successful save must return HTTP `201` with `{ "trip": { "id": "server-confirmed-id" } }` (a positive safe integer ID is also allowed). The browser must not display Saved unless this response contains a valid ID. A sample itinerary is never evidence of a save or AI generation.

Without backend Supabase configuration, a valid submission returns HTTP `503` with `TRIP_STORAGE_NOT_CONFIGURED` and makes no database query. With valid local configuration, the adapter inserts into the existing table and returns an ID only after the insert is confirmed. Automated tests inject fake clients and never use the real database.

## Run the local checks

Use Node.js 22 or later: the existing lockfile pins Supabase JS 2.118.0, whose declared minimum is Node 22. The older root `engines` value still says 18 and is documented here rather than changing dependency versions.

From the root of this **separate working copy**:

```bash
npm ci --ignore-scripts
npm run test:validation
npm run test --workspace=frontend
npm run test --workspace=backend
npm run build
```

`npm test` runs all three test groups. No live Supabase credentials are needed for these checks. If npm cannot write its default cache, choose an accessible cache directory; do not run npm as administrator just to bypass a cache-path problem.

The code's local test suites use Node's built-in test runner; no additional test dependencies were added. Installation lifecycle scripts are disabled. Do not enable them automatically if your environment cannot use the platform package binaries; investigate the specific failing dependency first.

## Environment and security boundaries

- Central backend configuration reads `backend/.env`, independent of the launch directory. The default listener is `HOST=127.0.0.1`; the Vite development proxy uses the same IPv4 loopback target.
- Only blank placeholders belong in `backend/.env.example`. Keep real `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in your own `backend/.env` when the storage step is ready.
- A Supabase secret/service-role key belongs only on the backend. Never put it in `VITE_*`, frontend source, a screenshot, chat, or a committed file.
- Health checks work without database configuration. The database client is initialized lazily, not when the application starts.
- This is a local development API. It does not yet enforce authenticated ownership or production abuse controls. CORS is not access control; do not publish an unauthenticated secret-key-backed save endpoint.
- Database errors and secrets must not appear in public API responses or logs.
- A request timeout cannot prove that the database did not commit. The client makes no automatic retries; uncertain outcomes must be checked before resubmitting to avoid duplicates.

## Confirmed existing-table mapping

The user supplied the complete existing `public.trips` definition. It is reference evidence only: no CREATE, ALTER, migration, or RLS/policy operation is included or executed.

| Existing database column | Stored value |
| --- | --- |
| `id` bigint identity, primary key | Omitted from the insert; generated by the database |
| `destination` text, required | Validated, trimmed `destination` |
| `start_date` date | Validated `startDate` |
| `end_date` date | Validated `endDate` |
| `budget` numeric | Validated numeric `budget` |
| `travelers` integer (default 1) | Validated integer `travelers` |
| `preferences` text | `JSON.stringify({ departureCity, currency, interests, dietaryNeeds, travelPace })` |
| `created_at` timestamptz (default `now()`) | Omitted from the insert; generated by the database |

For example, the `preferences` text contains a JSON string like this (synthetic values):

```json
{"departureCity":"Mumbai","currency":"USD","interests":["culture","food"],"dietaryNeeds":"vegetarian","travelPace":"balanced"}
```

This is TEXT, not a JSON/JSONB column; no database type change is needed. Future readers can parse this string as JSON. The existing table has no confirmed owner column; none is invented and no auth flow is added. Secret/service-role credentials may bypass RLS, so the endpoint stays a local prototype, not a production multi-user API.

The database's bigint ID is accepted only as a positive safe JavaScript integer or an exact nonblank string. Unsafe numeric IDs cannot produce a saved confirmation. If a project ever reaches IDs outside JavaScript's safe range, resolve exact serialization before retrying; the insert may already have committed.

## Local verification — one step at a time

**Start here:** extract the supplied working-copy ZIP into a new sibling folder named `anushka-travel-activity31`. Do not extract over your original project. No real `.env` file is included.

After that is confirmed, proceed in sequence:

1. Open a terminal in the extracted folder. Check `node -v`; use Node 22 or later for the already-locked Supabase version.
2. Run `npm ci --ignore-scripts`, then `npm test`, then `npm run build`. These tests use only local fake storage; they do not need Supabase secrets.
3. Privately copy your existing backend environment values into this copy's `backend/.env` (or copy its template first). Use `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Keep the key local; do not paste or screenshot it. Keep `HOST=127.0.0.1` and the default ports for this development check. The frontend can use the included `/api` proxy without a frontend `.env`.
4. Run `npm run dev`; open `http://localhost:5173`. Verify the health endpoint at `http://127.0.0.1:5000/api/health` returns `status: ok`.
5. Use clearly synthetic details, choose a non-default dietary need and travel pace, and click **Save trip preferences once**. This is the first real database write in the workflow. Wait for a confirmed trip ID; sample preview alone does not count.
6. In Supabase Table Editor, inspect that ID in the existing `trips` table. Confirm destination, dates, budget, and travelers, plus every value inside the JSON text in `preferences`. Verify `id` and `created_at` were generated. Do not alter the schema or policies.
7. Confirm a blank required field, end-before-start date, and invalid traveler count cannot submit. Check the separate sample preview does not create another row. The UI should not show Saved after an error, timeout, or malformed response.

If an error or timeout makes the write outcome uncertain, inspect the table before retrying. Do not delete any row or change policies without deliberate approval. Share only the sanitized result/ID and error code if troubleshooting is needed—never credentials or raw database internals.

**Completion gate:** a real confirmed row with all preference values correct, plus the local UI flow, is still required. Passing fake-client tests and a production build does not prove live Supabase persistence or browser behavior.
