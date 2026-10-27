# Local planner simplification

This change is not a claim of measured live speed or venue accuracy. No paid provider benchmark was run.

## Removed avoidable work

- A same-ID, successfully parsed **completed** research response with invalid evidence now stops as a known research failure. It no longer repeats retrieval until the eight-minute deadline. Transport, identity and status uncertainty still retain the paid handle; no automatic new submission is introduced.
- Research citation matching accepts HTTPS authority equivalence (hostname case/IDNA and default port443), not arbitrary redirects, query changes or unsupported sources. Display-title whitespace/length no longer rejects otherwise valid evidence. Citation spans and actual consulted-source requirements remain enforced. Closed diagnostic subreasons contain no response text or URLs.
- Subsequent sections and revisions no longer ask the model to repeat an immutable route already held by the server. The route stays in the input and is reattached before the same acceptance checks/public output. Old in-flight responses remain compatible only under strict old shape and route equality. First-section route generation is unchanged.
- Adaptive preference data now distinguishes original dates/budget from this section and computes the daily indicative allocation over **all remaining days**, not only the three-day section. The nested proposal instruction no longer conflicts with the enclosing JSON shape.

## More useful recommendations, same safeguards

The adaptive instruction requests concrete named dining/place candidates, neighborhood and routing context, why each fits, sensible group/per-person price estimates and practical alternatives. It rejects generic meal placeholders as recommendations, while explicitly forbidding invented venues, availability, prices or personal suitability. Research instructions favor actionable candidates and published information over a generic destination essay. Private preferences are not added to search queries.

HIGH reasoning, useful descriptions, strict structured output, approved six-tool/twelve-create allowance, owner isolation, date coverage, money arithmetic, route/rest validation and explicit recovery remain unchanged. There is no database migration or new service.

## Existing content visibility

Completed adaptive cards now retain the already-generated Dining field and offer a collapsed Day outline; revision candidates and saved/legacy timeline views show the same existing details. Timeline, cost, dietary/access disclaimers and explicit candidate acceptance stay intact. No HTML tables or new API calls are introduced. Mounted regressions first reproduced the hidden dining text and then verified it is visible without duplicating the old non-timeline fallback.

## Evidence and limits

Offline tests cover parser equivalence and hostile inputs, confirmed-terminal versus unknown recovery, old/new route-wire public equality, preview/revision parity, post-rehydration byte limits and correct remaining-budget allocation. A synthetic one-stay route removes142 output bytes; twelve short stays remove937 bytes (not token or latency measurements). Serial model reasoning and on-demand research can still dominate elapsed time. These changes must pass full regression/review and separately authorized release checks before any deployment.

Final local checks:1,526backend tests passed,7 optional SQL skips;529frontend tests passed serially; production build passed. Independent backend and presentation source review found no blocking issue. Updated synthetic mobile fixture has not yet been run in a browser; no new pixel or real-provider-quality claim. The existing >500kB bundle warning remains advisory. A separately identified stale-readiness/legacy-fallback risk is not changed by this patch.
