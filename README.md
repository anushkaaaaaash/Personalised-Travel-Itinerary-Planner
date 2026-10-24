# Personalized Travel Itinerary Planner

A Personalised Travel Itinerary Planner is an AI-powered application that helps users plan trips based on their travel preferences, budget, interests, and duration. It generates customised travel itineraries, recommends destinations and attractions, and helps users organise their trips efficiently.

The current planner uses React/Vite with the FastAPI backend in `backend-python/`.
Epics 3 and 4 include validated preference capture and history, dynamic prompts,
categorized AI recommendations, editable daily timelines, estimated route ordering,
and whole-trip/single-day feedback refinement. The original Express backend is
preserved for reference; root `npm run dev` still starts that legacy backend.

Groq refinement uses `openai/gpt-oss-120b`; generation/recommendations use the configured
Groq model (default `openai/gpt-oss-20b`). The backend enforces structured constraints,
but AI narrative, costs, opening hours and accessibility remain unverified estimates.
Itineraries are not saved automatically. Activity 5.1 adds explicit account-scoped full-itinerary CRUD in a separate table; legacy preference history remains project-wide in local mode. Public deployment is not configured. See [Activity 5.1 setup and verification](backend-python/ACTIVITY_5_1.md).

See [current completion and validation](EPICS_3_4_COMPLETION.md) and
[FastAPI setup](backend-python/README.md). Earlier Activity documents describe historical
checkpoints and may contain superseded installation/publication restrictions.

## Current Windows startup

Activity 5.2 adds private saved-itinerary detail pages and local summary/JSON/print exports. See [sharing, privacy and verification](ACTIVITY_5_2.md). The frontend requires Node 20 or newer.

From this repository root, using the existing `backend-python.venv` environment:

```powershell
.\backend-python.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend-python --host 127.0.0.1 --port 5000
```

In a second terminal run `npm run dev --workspace=frontend` and open
`http://localhost:5173/`. Keep `VITE_API_BASE_URL=/api` in local frontend configuration.
Do not run Express and FastAPI on the same port. Environment templates contain no
usable credentials; local configuration is excluded from Git. SQL and deployment
files marked `REVIEW_ONLY` require project-specific review and are never run automatically. The Activity 5.1 migration was manually applied in the configured QA project; deployment drafts remain unapplied. For full-itinerary authentication, use the explicit env-file startup in the Activity 5.1 guide.

## Historical Express setup and project reference

## Project structure

```
├── frontend/          React + Vite client
│   └── src/
│       ├── assets/        Images and static files imported by the UI
│       ├── components/    Reusable UI pieces
│       ├── pages/         Route-level screens
│       └── services/      API client helpers
├── backend/           Express API
│   └── src/
│       ├── config/        Environment and app settings
│       ├── controllers/   HTTP request handlers
│       ├── routes/        Route definitions
│       └── services/      Business logic and external APIs
└── package.json       Root workspace scripts
```

## Prerequisites

- Node.js 22 or later, with `node` and `npm` available in your terminal PATH
- The existing lockfile pins `@supabase/supabase-js` 2.118.0, which requires Node.js >=22; the older root `engines` declaration (>=18) is stale. Dependency versions have not been upgraded in this change.
- Confirm with `node -v` and `npm -v` before installing packages

If those commands are not recognized on Windows, install the LTS build from [https://nodejs.org](https://nodejs.org), then open a **new** terminal so PATH updates apply.

## Setup

1. Open this separate working copy. Keep your original folder unchanged.
2. Copy environment templates and fill in local values. **Do not commit `.env` files.**

   ```bash
   cp backend/.env.example backend/.env
   cp frontend/.env.example frontend/.env
   ```

   On Windows PowerShell:

   ```powershell
   Copy-Item backend/.env.example backend/.env
   Copy-Item frontend/.env.example frontend/.env
   ```

3. Install dependencies from the repository root (installs both workspaces):

   ```bash
   npm ci --ignore-scripts
   ```

4. Add any API keys only in `backend/.env`. The frontend must never store secret keys; it talks to the backend only.

## Development scripts

From the repository root:

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start frontend (Vite) and backend (Express) together |
| `npm run dev:frontend` | Start the Vite dev server only (`http://localhost:5173`) |
| `npm run dev:backend` | Start the Express API only (`http://localhost:5000`) |
| `npm run build` | Production build of the frontend |
| `npm start` | Run the backend (not a production-security deployment) |
| `npm test` | Run shared validation, frontend, and backend local tests |

You can also run `npm run dev` inside `frontend/` or `backend/`.

## Environment variables

Templates live in:

- `frontend/.env.example` — public Vite variables (prefix `VITE_`)
- `backend/.env.example` — server port, CORS origin, and secret API keys

Copy those files to `.env` in the same folders. Real keys stay out of source control via `.gitignore`.

## API health check

Once the backend is running, `GET http://localhost:5000/api/health` should return a JSON status payload. This is a scaffolding endpoint only.

## Next step: verify one real save locally

The adapter uses your confirmed existing `public.trips` table: dedicated trip columns plus JSON-encoded text in `preferences` for departure city, currency, interests, dietary needs, and travel pace. It lets Supabase generate `id` and `created_at`. No schema change, table creation, or policy change is needed or included.

Use this separate working copy and your own private `backend/.env`; do not send secrets through chat. Follow the staged local check in [ACTIVITY_3_1.md](ACTIVITY_3_1.md). One synthetic save must be verified against the table before Activity 3.1 can be marked complete. Automated tests use injected fakes only, even if local credentials exist.

Keep this development API local. There is not yet user authentication, ownership enforcement, or production rate limiting; CORS is not authorization. A backend-only Supabase secret/service-role key must never be exposed through frontend variables or the browser bundle.
