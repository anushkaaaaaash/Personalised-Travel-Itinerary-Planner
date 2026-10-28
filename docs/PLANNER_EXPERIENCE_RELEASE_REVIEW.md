# Planner experience release review (2026-10-28)

## Scope
Local follow-on to the deployed account-save tree (remote main
`41ecaa8a773eefb7097cadabf6e398ebe532ba50`; equivalent source tree to local
`5be6c05e2922323d6d2411b3c73d6e6867755069`). Local Git ancestry remains the
reconstructed source lineage, not the remote main ancestry; publish reviewed tree
changes atop the actual remote baseline.

- Personalised Travel Planner branding and instant, explicitly prewritten examples.
- Continuous Day 01, Day 02… headings with calendar dates, clearer current progress,
  concise usage disclosure, and explicit safe restart/reconciliation controls.
- Rough whole-trip timing guidance based on limited recent timing observations,
  never a countdown or guaranteed completion time; elapsed time means this visit.
- PDF downloads for retained plans, saved account trips and validated full snapshots.
- Small confirmed research-handoff scheduling improvement and private timing logs.

## User-visible limits and honest claims
- Removing visible section breaks does not change the internal three-day generation
  checkpoints. No model effort, research capability, useful descriptions or output
  limits were reduced. A nine-day trip is not newly generated in one request.
- The scheduler test removes one five-second idle wait in an isolated research
  handoff; no production generation speedup or new paid benchmark is claimed.
- Examples are static inspiration, not live research or instant personalized AI.
  Dates remain unset and budgets editable; examples are not current price quotes.
- Returning later depends on retained account/temporary-plan identity and expiry;
  work may pause for approval. Downloading a PDF does not save an account copy.
- PDF export is fail-closed for changed snapshots, inconsistent dates/totals or
  limits; partial retained trips are labelled partial. Oversized exports may fail
  rather than silently truncate. The renderer currently permits 2 MiB serialized
  input, 24 MiB output and cooperative 30-second/2,000-page bounds, one export at a
  time per process. Concurrent requests get a retry-later response. Cancellation
  does not forcibly terminate an in-progress layout operation.
- PDFs include personal activity/travel notes; users should review before sharing.
  Standard Latin/Greek/Cyrillic fonts are embedded; CJK depends on viewer support.
  Unsupported characters are explicit Unicode code points, not silently dropped.
  Complex-script shaping and tagged PDF/UA accessibility are not guaranteed.

## Review and release gates
Independent source reviews cover latency, UI ownership/ambiguity handling and PDF
authorization/resource/format safeguards. PDF render spot checks show readable
headings, dated days, notes and expense tables without clipping in the inspected
synthetic pages. A 24-day fixture verifies pagination/content retention.

Actual updated mobile/desktop browser pixels remain a separate CI review gate;
local browser startup was blocked by the execution environment. Prior release
screenshots are not proof of this changed UI. No current user's itinerary, live
provider generation or production database mutation was used for these tests.

Database migration SQL and native SQL workflow are unchanged from the reviewed
account-save release. New code does not require a production migration. Final
source must pass exact-head CI, visual review and the existing controlled release
process before deployment; publishing permission does not waive safety checks.

## Final integrated local verification
- Python: **1,625 passed, 4 skipped**. The four skips are explicitly opt-in real
  PostgreSQL archive/concurrency/migration cases; no local hosted database was used.
- Frontend: **587 passed** in serial, including PDF fixture parsing and auth races.
- Shared validation: **27 passed**; legacy Node backend: **81 passed**.
- Deployment guards: **35 passed**.
- All three pinned PGlite SQL suites passed. Native SQL source/workflow is unchanged;
  prior native CI evidence is a baseline, not a fresh result for this release head.
- Production build, public-asset pattern check and `git diff --check` passed.
  Existing bundle-size and test-renderer deprecation warnings are not hidden.
- Independent reviewer cleared latency, UI and final PDF source; independently
  executed the targeted safety tests. Full-suite counts above are integration runs.

## Packaging correction before publication
Release review caught that the deny-by-default Docker context omitted the PDF
font directory. The context now permits exactly `DejaVuSans.ttf`,
`DejaVuSans-Bold.ttf` and their `LICENSE.txt`, with descendant and final secret
denials preserved. The executable pinned Moby matcher regression passes with the
fix and fails against the prior ignore file on the missing required font.

A new CI smoke executes application import and actual embedded-font PDF rendering
inside the built non-root, no-network production image. Its synthetic script also
passes locally; deployment guards (35 tests), YAML parsing and whitespace checks
pass. Application/frontend bytes are unchanged from the full suite above. Docker
is not installed in this execution environment, so actual image execution remains
an explicit exact-head CI gate; local PDF success is not claimed as container proof.
