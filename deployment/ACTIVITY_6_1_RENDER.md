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
prove the current dashboard checkout SHA. Subsequent user-supplied Render Settings
show the existing repository, branch `main`, connected Git credentials, Python 3,
Free compute, Oregon, the expected root/build/start command, `/api/health`,
Auto-Deploy **Off**, and PR Previews **Off**. This supersedes the earlier inference
that the service still lacked a Git-provider connection. No new OAuth connection
is needed based on this evidence. Account identifiers and deploy-hook values are
intentionally omitted.

The pasted Settings header showed `df77aa4`, whereas earlier successful deployment
evidence showed `0fc9804`. This discrepancy may be a stale header; neither a rollback
nor the current runtime SHA is established by it. Verify the most recent successful
deployment's commit in Events before claiming a specific version is running.

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
| Continuous deployment | Git credentials connected; Auto-Deploy Off. Approval to enable After CI Checks Pass and successful automatic-deploy evidence remain pending |
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
2. Git credentials are already connected in the supplied Settings evidence. Do not
   reconnect GitHub, grant new repository permissions, or create another service.
   Request approval to change only Auto-Deploy from Off to After CI Checks Pass.
3. After explicit approval, select **After CI Checks
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
