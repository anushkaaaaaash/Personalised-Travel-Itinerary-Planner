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

At 15:06:34 on 2026-10-25, the user supplied the saved setting text
`autoDeployTrigger After CI Checks Pass` after approving only that change.
This supersedes the earlier Off setting. It is user-provided saved-setting
evidence, not an autonomous dashboard observation. No new automatic deployment
event has yet been demonstrated. Free compute and PR Previews Off remain the
authorized configuration; preview-origin permissions are unchanged.

The pasted Settings header showed `df77aa4`, whereas earlier successful deployment
evidence showed `0fc9804`. This discrepancy may be a stale header; neither a rollback
nor the current runtime SHA is established by it. Verify the most recent successful
deployment's commit in Events before claiming a specific version is running.

| Course item | Status | Existing implementation / remaining gap |
|---|---|---|
| Backend hosted on Render | PASS | Existing live Free web service; reuse it |
| GitHub source, main branch | PASS | User Settings show same repository/main and connected Git credentials |
| Node runtime wording | PASS (adapted) | Actual backend is Python/FastAPI; the supplied pip/Gunicorn instructions are themselves Python. Literal Node selection is intentionally not followed |
| Root/build | PASS | `backend-python`; `pip install -r requirements.txt` |
| Start/port | PASS (adapted) | Production factory below binds `0.0.0.0` and Render's `$PORT`; Gunicorn example is not copied |
| Environment configuration | PASS (functional) | Existing approved Groq/Supabase configuration; live auth/health and historical generation evidence. Private dashboard values not independently inspected |
| Closest region | BLOCKED | Oregon confirmed; user proximity not established, no relocation authorized |
| CI | PASS | Push/PR workflow runs Python, JavaScript, build, bundle and tracked-env checks; main CI passed before enabling auto-deploy |
| CI-gated auto-deploy setting | PASS (user evidence) | User reports saved After CI Checks Pass; no autonomous dashboard verification |
| Observed automatic deployment (additional confidence check) | Not observed; not an explicit course step | An approved eligible main change and matching automatic Render event would provide additional evidence, but no extra deployment is required solely for this audit |
| Autoscaling | BLOCKED (excluded Free scope) | Not configured; Pro-or-higher feature. User explicitly said not to add paid/unavailable scaling |
| Current runtime commit identity | BLOCKED | Conflicting header evidence; health alone cannot identify the running SHA |

PASS (adapted) establishes correct deployment for this actual application, not an
assessor waiver of literal sample commands. BLOCKED means missing evidence or an
approval/scope boundary, not a known application failure. No observed requirement
currently has a demonstrated runtime FAIL. Core hosting and CI-gated configuration
are supported by the evidence above; region, scaling scope and runtime-SHA limits
remain explicit rather than an unqualified 100% claim.

The supplied Activity 6.1 story mentions continuous deployment, but its steps ask
for service configuration, deployment and Live status. They do not explicitly
require a separate push-triggered deployment demonstration. Connected Git
credentials and the user-confirmed saved CI-gated setting support the configuration
requirement. Lack of an observed automatic event is a verification limit, not an
additional mandatory course task. The earlier stricter completion wording was
incorrect and is superseded here.

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

## Optional additional operational verification

1. Open the **existing service → Settings**. Inspect source/repository/branch and
   Auto-Deploy, plus the most recent successful deployment commit. Share field
   names/nonsecret settings only; never reveal environment values or deploy-hook URLs.
2. Git credentials are already connected and the user reports saving the approved
   **After CI Checks Pass** setting. Do not reconnect GitHub, grant permissions,
   repeat the settings change, or create another service. Keep branch `main`, Free
   compute, PR Previews Off, and root/build/start/env/origins unchanged.
3. PR #10 remains draft and unmerged. Its changed files are under `deployment/`,
   outside Render's `backend-python` root. Render documents that root-directory
   scoping excludes outside-root changes from auto-deploy triggers. Therefore a
   merge of this PR must NOT be promised as an automatic-deployment test; additional
   configured Build Filters may further restrict eligible changes. Inspect those
   filters read-only before selecting a test change. Do not alter them without approval.
4. If additional end-to-end evidence is requested, verify a subsequently approved main commit has successful GitHub checks and a
   corresponding successful automatic Render deployment of the same SHA. Do not
   create an empty commit just to trigger deployment or claim manual deployment
   proves continuous deployment. Confirm health/auth/access boundaries afterward.

The existing reviewed backend tests from PR #9 are already on main and cannot
prove a new trigger after this setting change. No currently unmerged, necessary
backend-root change has been identified in this audit. Wait for a genuinely needed,
reviewed change within `backend-python` that also matches the actual build filters,
and obtain merge/deployment-test approval then. Do not relocate this document,
touch runtime files, add a dummy commit, or manually deploy merely to manufacture
an automation claim. A manual deployment is not evidence of CI-gated automation.

If any source/permission/plan change is required, stop for approval. Preserve the
current successful service while investigating. No credentials, billing, data,
origins or security policies change as part of this repository documentation PR.
Do not withhold the core deployment/configuration result solely because the
optional automatic-trigger test has not run. Autoscaling remains separately
unfulfilled if assessed literally, but is excluded by the user's Free-only scope;
no paid upgrade is implied. Region proximity and exact current runtime SHA remain
unverified. No extra production deployment is justified by this documentation fix.

## References checked 2026-10-25

- [Deploys and CI gating](https://render.com/docs/deploys)
- [Web services and public repository limitations](https://render.com/docs/web-services)
- [Scaling availability](https://render.com/docs/scaling)
- [Free instance limitations](https://render.com/docs/free)
- [Root-directory scoping and build filters](https://render.com/docs/monorepo-support)
