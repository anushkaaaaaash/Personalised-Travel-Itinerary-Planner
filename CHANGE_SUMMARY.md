# Activity 3.1 — implementation checkpoint

## Result

Implemented preference capture, validation, submission, and the adapter for the **existing** Supabase `public.trips` table in this separate copy. **Activity 3.1 is not yet complete:** a real local save and browser verification using your private backend configuration remain to be checked.

### Start with just this step

Extract this ZIP into a new sibling folder, `anushka-travel-activity31`. **Do not extract over your original project.** No real `.env` is included. Keep your existing original project and ZIP unchanged.

After extraction, use the one-step-at-a-time local sequence in `ACTIVITY_3_1.md`. Do not send your secrets through chat.

## What changed

- Initialized `dietaryNeeds` to no preference and `travelPace` to balanced, retaining the existing form and interest options.
- Added one shared strict validation contract used by frontend, Express, and the storage adapter. Added clear field errors, typed numbers, real-date checks, and rejection of unknown fields/shapes.
- Replaced the health-check/fake-delay submission with `POST /api/trips`. Loading locks prevent repeated submissions; edits clear old success. Timeout/network failures never claim success or trigger automatic retries.
- Success requires HTTP 201 plus a confirmed trip ID. Bigint IDs are not silently rounded. Saving preferences does not generate an itinerary.
- Kept a separate optional sample preview with explicit sample labels and a 14-day rendering cap. It neither saves nor applies dietary/pace recommendations.
- Added a schema-specific adapter that inserts only `destination`, `start_date`, `end_date`, `budget`, `travelers`, and JSON-encoded TEXT in `preferences`. The JSON carries `departureCity`, `currency`, `interests`, `dietaryNeeds`, and `travelPace`. The database generates `id` and `created_at`.
- Centralized environment loading, made the database client lazy, preserved health without secrets, and kept the development backend on `127.0.0.1`. Secrets remain backend-only. Database/network details are not exposed to users or logs.
- Added test scripts, automated tests, and documentation. **No dependency versions or lockfile were changed.** The already-locked Supabase library needs Node 22+, although the pre-existing root `engines` declaration still says 18.

## Tested

Stage 1 was verified before API integration: **24 shared validation tests + 26 frontend initial-state/payload tests passed.**

Final checks:

| Check | Result |
| --- | --- |
| `npm run test:validation` | 24 passed |
| `npm run test --workspace=frontend` | 60 passed, including 6 server-rendered React markup checks |
| `npm run test --workspace=backend` | 76 passed |
| `npm test` | All 160 passed; no failures |
| `npm run build` | Production frontend build passed |
| Cross-layer loopback test | Frontend payload/client → Express → real mapping code → fake Supabase chain passed |
| Exact row + JSON TEXT round trip | Passed, with generated ID/timestamp columns omitted |
| Original baseline preservation | All 33 original file hashes unchanged; no original files added/deleted |
| Dependency lockfile | Byte-identical to the uploaded baseline |
| Source/template secret-pattern scan | No filled secret pattern found |

Tests use injected fake storage or an explicitly empty configuration even if a developer has real local credentials. No automated test calls Supabase. Installation used `npm ci --ignore-scripts` with an accessible temporary npm cache; no install lifecycle scripts were run. The final check environment was Node 24.19.0 / npm 11.9.0.

## Not tested / not done

- **No live Supabase insert or persisted-row check:** private credentials were neither requested nor used here. Verify one synthetic local save and all stored values before marking Activity 3.1 complete.
- **No live browser/visual end-to-end verification:** browser launch was blocked by executor restrictions. React SSR checks and production build passed, but do not substitute for a real browser run.
- No CREATE/ALTER/table replacement, RLS/policy change, GitHub push, new repository, deployment, or authentication implementation.
- This remains a local development prototype. A secret/service-role key can bypass RLS; public multi-user deployment needs separate authentication, ownership, and abuse controls.

## Source changes compared with the preserved baseline

Modified existing files:

- Root: `README.md`, `package.json` (test scripts only; dependency declarations unchanged).
- Backend: `package.json`, `.env.example`, `src/index.js`, `src/routes/index.js`, `src/config/env.js`, `src/config/supabase.js`.
- Frontend: `package.json`, `.env.example`, `vite.config.js`, `src/index.css`, `src/pages/PlannerPage.jsx`, `src/services/api.js`, `src/utils/buildPreviewItinerary.js`, and the three existing components `PlannerForm`, `ItineraryResults`, `SiteHeader`.

Added files:

- Shared: `shared/tripPreferences.mjs`, `shared/test/tripPreferences.test.mjs`.
- Backend: `src/app.js`, `src/controllers/tripController.js`, `src/services/tripService.js`, and three `test/*.test.js` files.
- Frontend: `src/utils/tripPreferences.js`, `src/services/tripSubmission.js`, and five `test/*.test.js` files.
- Documentation: `ACTIVITY_3_1.md`, `CHANGE_SUMMARY.md`.

The remaining 15 baseline files are byte-for-byte unchanged, including `package-lock.json`, `.gitignore` files, existing app/bootstrap files, health controller, itinerary-service placeholder, static placeholders, and the preserved `backend/Untitled` note. The original sanitized baseline folder itself was not edited.
