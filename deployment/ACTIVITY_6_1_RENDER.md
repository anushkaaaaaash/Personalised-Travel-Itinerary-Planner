# Activity 6.1 — existing Render backend

## Scope and evidence

Reuse `anushka-travel-planner-api` at
https://anushka-travel-planner-api.onrender.com in the existing workspace.
Repository: https://github.com/anushkaaaaaash/Personalised-Travel-Itinerary-Planner
with deployment branch `main`. Do not create another service or replace it with
the template's example name. This document does not configure Render.

On 2026-10-25, read-only public checks returned health 200, production auth enabled,
saved-only mode, anonymous saved-itinerary access 401 and legacy history 404.
Earlier user-run production generation acceptance is recorded in
ACTIVITY_5_3_5_4.md. These checks do not expose environment values or independently
prove the current dashboard checkout SHA, region, Git integration or auto-deploy
setting. Current operational evidence is a public-Git-URL source with manual
deployment; dashboard verification remains pending.

| Course item | Existing implementation / remaining gap |
|---|---|
| Backend hosted on Render | Existing live Free web service; reuse it |
| GitHub source, main branch | Same existing repository; no new repository |
| Node runtime wording | Intentional adaptation: actual backend is Python/FastAPI; the supplied pip/Gunicorn instructions are themselves Python |
| Root/build | `backend-python`; `pip install -r requirements.txt` |
| Start/port | Production factory below; binds `0.0.0.0` and Render's `$PORT`, not hardcoded 5000 |
| Environment configuration | Existing approved Groq/Supabase public configuration; no custom JWT secret or service-role key needed for user operations |
| Closest region | Previously selected Oregon; proximity to users not established, no relocation authorized |
| CI | Existing push/PR workflow runs Python, JavaScript, build, bundle and tracked-env checks; no new workflow needed |
| Continuous deployment | Not yet verified/enabled through a connected Git provider; operational approval required |
| Autoscaling | Not configured; Pro-or-higher feature, outside the approved Free demo scope |

Retain Python 3.13.7 and the reviewed start command:

```text
uvicorn app.production:create_production_app --factory --host 0.0.0.0 --port $PORT --workers 1 --no-access-log
```

The factory validates configuration before serving and preserves auth/ownership
guards. Gunicorn is not installed; blindly replacing the command with the course
example bypasses this explicit startup check. One worker is intentional because
current request/cost quotas are in-process, not distributed. Do not enable scaling
without reviewing those limits. Render Free is a course demo with sleep/cold-start
limits, not an always-on production availability promise.

## Remaining operational step — approval first

1. Open the **existing service → Settings**. Inspect source/repository/branch and
   Auto-Deploy, plus the most recent successful deployment commit. Share field
   names/nonsecret settings only; never reveal environment values or deploy-hook URLs.
2. Render's official docs state that public-Git-URL services require manual deploys;
   auto-deploy requires a connected Git provider. If this service still uses a
   public URL, request approval for the exact GitHub integration/repository access
   and any existing-service source change. Prefer access to this repository only.
   Do not assume a toggle alone is sufficient, accept broader permissions, or
   create a replacement service if reconnection is unavailable.
3. After explicit approval and supported reconnection, select **After CI Checks
   Pass**, keeping branch `main`, Free compute, root/build/start/env/origins unchanged.
   Approval must acknowledge that later main changes may deploy automatically.
4. Verify a subsequently approved main commit has successful GitHub checks and a
   corresponding successful automatic Render deployment of the same SHA. Do not
   create an empty commit just to trigger deployment or claim manual deployment
   proves continuous deployment. Confirm health/auth/access boundaries afterward.

If any source/permission/plan change is required, stop for approval. Preserve the
current successful service while investigating. No credentials, billing, data,
origins or security policies change as part of this repository documentation PR.
Activity 6.1 remains partially complete until continuous deployment is verified
or the course explicitly accepts manual deployment. Autoscaling is separately
unfulfilled if the assessment requires it; no paid upgrade is implied.

## References checked 2026-10-25

- [Deploys and CI gating](https://render.com/docs/deploys)
- [Web services and public repository limitations](https://render.com/docs/web-services)
- [Scaling availability](https://render.com/docs/scaling)
- [Free instance limitations](https://render.com/docs/free)
