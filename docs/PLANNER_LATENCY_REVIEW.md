# Output-preserving planner latency review

## Observed production evidence (2026-10-27)
Sanitized logs showed completed-request elapsed waits of roughly 107–249 seconds, with local acceptance validation taking 7–9 milliseconds. `provider_wait` includes provider execution, polling and scheduler delay; it is not a pure provider execution measurement. No request IDs or trip contents were inspected. Modest aggregate CPU/memory usage did not indicate sustained resource pressure. Repeated `BACKGROUND_INVALID_RESPONSE` retrieval records were also present; existing logs cannot establish the exact rejected shape or attribute these to a particular user's trip.

## Narrow fixes
- Reuse the server-verified identity only within the same ASGI request, exact authentication service and bearer token. Every new request still verifies with Supabase; there is no cross-request token cache or new revocation window. Adaptive requests previously verified twice, in middleware and route.
- Allow bounded serial immediate follow-ups after durable completion/handoff rather than always sleeping five seconds. Ordinary in-progress polls, uncertain operations and failures retain backoff. No parallel creates, automatic paid retries or increased allowances.
- Parse supported explicit `final_answer` messages separately from commentary; retain strict legacy single-answer handling, refusals, identity and size limits. Recognize documented terminal incomplete reasons instead of treating them as unconfirmed retrievals.
- Recognize actually consulted open/find tool URLs, with the same public-URL and citation provenance checks. Missing source metadata never establishes a citation.
- Emit only closed diagnostic reason categories, never response bodies, user notes, IDs or credentials.

These changes preserve HIGH reasoning, final public structure, descriptions, research budget, date/budget/route acceptance and owner isolation. They do not guarantee short provider execution. No paid benchmark was run and no numerical real-world speed improvement is claimed.

Official response shapes: https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_output_message.py ; https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response.py ; https://github.com/openai/openai-python/blob/main/src/openai/types/responses/response_function_web_search.py .

## Deliberately not changed
No removal of correctness checks, weaker authentication, larger concurrency, silent research reuse, lower reasoning, shortened descriptions or extra model calls. Prompt restructuring and removing repeated immutable strategy output require separate contract work and were not bundled as speculative speedups.

## Verification and limits
Offline tests reproduce documented response-shape failures, preserve strict final acceptance and exercise request-local authentication and SQLite restart recovery. A synthetic serial handoff test removes 15 seconds of scheduler sleep across three transitions (25 to 10 seconds), with the same two creates and one accepted result; this is not a live latency benchmark. Explicit streamed commentary switches the known response to retrieve-only mode and hides provisional drafts, never creates a replacement. Previously failed jobs are not automatically retried; an older stream whose commentary metadata is no longer replayed is not guaranteed recoverable by this fix. Deployment must wait for the existing quiescence gate; no database upgrade is needed.
