# Personalized Travel Itinerary Planner

A Personalised Travel Itinerary Planner is an AI-powered application that helps users plan trips based on their travel preferences, budget, interests, and duration. It generates customised travel itineraries, recommends destinations and attractions, and helps users organise their trips efficiently.

This separate working copy includes the existing React (Vite) planner, strict preference validation, and a Node.js (Express) submission API. **Activity 3.1 is not yet verified end to end:** the Supabase adapter maps to the confirmed existing `trips` schema, but a real save must still be checked locally using your own backend configuration. Without that configuration, the API returns a safe `503`; it never pretends a trip was saved. Itinerary previews are local samples, not AI-generated plans.

See [ACTIVITY_3_1.md](ACTIVITY_3_1.md) for scope, verification, and the remaining database step.

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
