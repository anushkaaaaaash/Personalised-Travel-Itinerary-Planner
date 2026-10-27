# Planner duration/recovery regression

The generation contract is intentionally bounded to 1–14 inclusive days. Shared
preference validation previously accepted a longer date range in the stepper,
while only the background submit handler routed it back to editable dates.
Production uses synchronous generation today. That path rejected the range in
its adapter, then rendered a generic time-related heading and a Retry button
which repeated the same invalid request locally. Reload does not make an
unsupported range valid. No dates should be silently shortened.

The stepper now enforces the planning-only limit before Review, and submission
revalidates it for both synchronous/background modes and restored Review state.
The original values remain editable, with the selected inclusive day count.
Saved preference schemas and records are not rewritten or deleted. Failure
presentation offers editing instead of an unsupported-input retry loop.

The reported stale-result concern is also covered by mounted regressions:
changing destination clears the previous result; a cancelled late response
cannot replace a newer result; a fresh mount starts without an old plan. These
paths did not reproduce a separate stale cache bug in offline testing. Further
reports of stale saved records should identify the exact load/navigation action
rather than assume this date-validation issue explains every state problem.

Country palettes already applied to the reported review/error screens. Tests
cover selected-country loading/error/result transitions, edits to another country,
unknown-destination fallback, saved-route changes and remount cleanup. Synthetic
browser QA exercises the 24-day rejection and previous-plan/new-destination flow.
No provider calls, user account writes, or saved-trip deletion are required.

Raising the cap to 30 is not part of this fix: structured output, output-token,
response-size, scheduling and request-duration bounds require separate validation.
