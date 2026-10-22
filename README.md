# Personalized Travel Itinerary Planner

A Personalised Travel Itinerary Planner is an AI-powered application that helps users plan trips based on their travel preferences, budget, interests, and duration. It generates customised travel itineraries, recommends destinations and attractions, and helps users organise their trips efficiently.

This repository currently contains the **initial project structure and configuration** for a React (Vite) frontend and a Node.js (Express) backend. Application features will be implemented in later steps.

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

- Node.js 18 or later, with `node` and `npm` available in your terminal PATH
- Confirm with `node -v` and `npm -v` before installing packages

If those commands are not recognized on Windows, install the LTS build from [https://nodejs.org](https://nodejs.org), then open a **new** terminal so PATH updates apply.

## Setup

1. Clone the repository and open the project folder.
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
   npm install
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
| `npm start` | Run the backend in production mode |

You can also run `npm run dev` inside `frontend/` or `backend/`.

## Environment variables

Templates live in:

- `frontend/.env.example` — public Vite variables (prefix `VITE_`)
- `backend/.env.example` — server port, CORS origin, and secret API keys

Copy those files to `.env` in the same folders. Real keys stay out of source control via `.gitignore`.

## API health check

Once the backend is running, `GET http://localhost:5000/api/health` should return a JSON status payload. This is a scaffolding endpoint only.

## Next steps

- Add itinerary, destination, and preference pages on the frontend
- Implement itinerary generation and recommendation services on the backend
- Connect the client `src/services` layer to those APIs
