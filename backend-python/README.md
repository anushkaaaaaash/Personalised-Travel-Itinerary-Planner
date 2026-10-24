> Current Activity 5.1 full-itinerary storage, local authentication startup, and verification are documented in [ACTIVITY_5_1.md](ACTIVITY_5_1.md). The earlier checkpoints below are historical.

# FastAPI preference capture + structured prompts

This is an additive backend for the **separate FastAPI working copy**. The existing
Express backend stays available as reference; do not run both on port 5000.
This source is integrated on a review branch; see ../EPICS_3_4_COMPLETION.md for current scope and validation.

## What is implemented

- `GET /api/health`: identifies this backend as `fastapi`.
- `POST /api/trips`: strict Pydantic request validation, then a single insert into
  the existing `public.trips` table through Supabase's REST API. Returns `201`
  only with a confirmed positive database ID. No retries, schema changes or DDL.
- `POST /api/prompts/itinerary`: Activity 3.2 deterministic structured prompt,
  with separate system/user messages, roles, constraints and preference context.
  **Does not save, generate an itinerary, contact AI, or incur AI charges.**
- `/docs`: interactive API documentation with the request/response schemas.

The React form now also captures optional travel style and practical mobility
needs. Blank means unspecified, not a medical assumption. Older payloads without
these two optional fields remain valid. All extra preferences are serialized
inside the existing `preferences` TEXT column; it is not changed to JSONB.
The existing columns remain `destination`, `start_date`, `end_date`, `budget`,
`travelers`, and `preferences`; `id` and `created_at` use database defaults.

**Budget meaning:** the entered amount covers the whole group and whole trip.
The prompt derives an indicative group daily allocation from the inclusive date
range. It is not a per-person amount. Balanced pace maps to moderate pacing.
The model will be asked to flag uncertain costs, insufficient budgets and
unverified accessibility rather than promise them. Actual AI compliance still
requires Activity 3.3 testing; prompt instructions are not a security guarantee.

## Windows setup (in the separate copy only)

The `.venv` already created by the user should be retained. These commands do not
activate it, so no PowerShell execution-policy change is needed. Run from the
separate project root:

```powershell
cd "D:\project travel\Personalised-Travel-Itinerary-Planner-FastAPI"
.\backend-python.venv\Scripts\python.exe -m pip install -r .\backend-python\requirements.txt
.\backend-python.venv\Scripts\python.exe -m pytest -c .\backend-python\pytest.ini .\backend-python\tests
npm.cmd test
npm.cmd run build
```

Node is required for the existing React frontend and two cross-language Python
tests. A skipped cross-language test is not evidence of passing integration.
Pinned dependencies are in `requirements.txt`. Do not use `npm audit fix --force`.
The existing frontend remains on Vite 6.4.5; no new JS dependency is needed.

## Run two terminals

First stop any existing dev servers with Ctrl+C. Do **not** use root `npm run dev`
for this FastAPI copy: that still starts the preserved Express reference server.

Terminal 1, from the separate project root:

```powershell
.\backend-python.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir .\backend-python --host 127.0.0.1 --port 5000
```

Terminal 2, from the same separate project root:

```powershell
npm.cmd run dev --workspace=frontend
```

Open `http://localhost:5173/`. The existing Vite `/api` proxy points to port 5000.
Check `http://127.0.0.1:5000/api/health` shows `"backend":"fastapi"`.

## Safe configuration

Only an explicit save reads the separate copy's existing `backend/.env`.
It expects `SUPABASE_URL` and `SUPABASE_SECRET_KEY`, the same names as Express.
It does not read the original project's folder. OS environment values override
that file. Do not paste keys into chat, screenshots, source code or the frontend.
Never give a secret/service-role key a `VITE_` prefix.

The adapter allows hosted HTTPS `*.supabase.co` URLs only, never redirects or
retries an insert, and never logs/returns raw database errors. New `sb_secret`
keys use `apikey`; legacy service-role JWTs also use the authorization header.
No credentials are shipped in this patch. Tests use fake values and transports.
Missing config deliberately produces 503 rather than claiming success.

## Verify Activity 3.2 without any database/AI call

Open `http://127.0.0.1:5000/docs`, expand **POST /api/prompts/itinerary**, click
Try it out, and use `examples/trip-preferences.json` as the request body.
Execute should return 200, `generated: false`, `tripDays: 3`, and daily group
budget `10000.00`. Inspect both messages and each preference. Changing a field
must change the corresponding prompt context; invalid fields must return 400.
This endpoint is distinct from POST /api/trips and does not insert a row.

## Real save acceptance (still pending on the user's machine)

1. Verify the FastAPI health response above.
2. On the React form, try missing/invalid inputs: save must be blocked.
3. Enter valid values plus optional style/mobility notes; move Back/Next and
   confirm values persist. Review then click Save **once**.
4. Match the success ID and all values to the row in existing Supabase `trips`.
   Inspect the TEXT preferences JSON for both new fields. No table change.
5. If a request times out or confirmation fails, check the table before retrying:
   an insert may have succeeded even when its response was lost.

Tests and a build alone do not mark the activity complete. Activity 3.3, live AI
provider/model selection, real recommendation generation, deployment, auth/user
ownership and any remaining SkillWallet-specific requirements are not completed.
This is a loopback-only local prototype. Do not publicly deploy a no-auth API
that uses a privileged Supabase key. No RLS policies or accounts were changed.

## References used

- FastAPI testing: https://fastapi.tiangolo.com/tutorial/testing/
- Pydantic strict mode: https://docs.pydantic.dev/latest/concepts/strict_mode/
- Supabase REST API: https://supabase.com/docs/guides/api
