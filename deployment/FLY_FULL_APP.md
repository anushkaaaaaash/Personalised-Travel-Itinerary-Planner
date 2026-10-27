# Same-origin Fly full application candidate

Uses the already approved single shared CPU/512MB Singapore Machine. No additional
service, volume, database, account, secret or recurring purchase is introduced.
The frontend build runs in a separate Node image stage; only public `dist` files
join the non-root Python runtime. Build-time API base is the relative `/api`, under
an explicit same-origin build mode; secret-like VITE settings remain forbidden.

The optional SERVE_FRONTEND mode permits unauthenticated GET/HEAD only for root,
index, itinerary-detail shell and narrowly named public assets. API paths remain
under existing authentication, ownership, Host/origin and no-store guards. Missing
assets, docs, environment files, source maps, unknown paths and path traversal do
not get an HTML fallback. Missing frontend builds fail startup. No Vercel setting
or redirect is needed to use the Fly URL, and the old Vercel site is not deleted.

## Runtime configuration to coordinate

The Fly file sets FRONTEND_ORIGIN to the Fly HTTPS origin and retains the existing
Vercel origin as the single additional explicitly allowed origin. If an existing
Fly secret overrides FRONTEND_ORIGIN, parent must update that non-secret value to
the Fly origin as part of deployment; do not print or rewrite other secrets.
SERVE_FRONTEND=true and FRONTEND_DIST=/app/frontend-dist are image/runtime values.
No Supabase auth redirect or saved-data migration is required by these changes.

This publishes the complete UI and API on one origin, but is NOT proof that paid
itinerary generation works. PLANNING_JOBS_ENABLED remains false while the scoped
storage startup failure is unresolved; the synchronous generation path remains
bounded and previously timed out. The rejected unpublished diagnostic patch is
not included. A complete release still requires resolving the storage path,
enabling already-approved guarded background setup, and an explicitly approved
synthetic real-generation acceptance run. Never call a root/health200 a successful
itinerary test. Parent owns secrets, activation and live acceptance authorization.

## Offline/CI checks

Tests cover public HTML/assets/direct detail links, GET/HEAD, Host/origin rejection,
protected APIs, source/config/traversal denial, symlink denial, missing-build fail
closed, and explicit relative-API build configuration. Pinned actual Docker matcher
checks the expanded context excludes secrets and legacy/server/test/data files.
The existing Fly container CI now builds both stages, runs with no network and
synthetic settings only, fetches real HTML/JS and detail route, then checks protected
API rejection. No external provider call is made by this workflow.
