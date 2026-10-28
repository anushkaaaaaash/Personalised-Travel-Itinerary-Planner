# Planning latency: measured limits and local improvement

## Evidence (2026-10-28; read-only production log review)
Three recent completed section responses were reported by the release operator at
06:18:04, 06:21:02 and 06:25:11 UTC. The aggregate `provider_wait` values were
214.634, 178.189 and 248.705 seconds (641.528 seconds total); validation took
29, 7 and 8 milliseconds. Logs deliberately omit owner, request and destination
identifiers, so these cannot definitively be attributed to the reported nine-day
Mumbai–Delhi trip. No provider diagnostic error was visible after 06:10 in the
reviewed window. No new generation/provider call was made for this investigation.

`provider_wait` is submission-to-terminal-retrieval elapsed time, not measured
model compute: it includes network, polling and scheduler delays. Successful
research previously lacked phase timing, so its presence or duration cannot be
inferred from these logs. Three samples are not a latency distribution or reliable
remaining-time estimate. The eight-minute limit is per response, not per trip.

## Why not parallelize or shorten the result?
Nine days normally require three sequential sections of up to three days. Later
sections consume the accepted boundary, budget, journey strategy and prior
activities. Parallelizing them would bypass those continuity constraints. Model
reasoning, descriptions, output limits, research capability and admission limits
are unchanged. Reducing those without quality evaluation is not a demonstrated
safe fix for this run.

## Local-only change
A confirmed durable on-demand research transition now signals the existing
bounded, fair immediate-handoff scheduler. This removes one ordinary five-second
sleep before the next available work, without replaying a create or overriding
leases, quota, pause or cancellation checks. It is a small scheduling improvement,
not a claimed remedy for minutes of provider latency. An uncertain transition,
wrong section ID or unrelated result does not set the hint. Existing four-tick
burst bound and round-robin fairness remain unchanged.

Closed-field aggregate timing now also covers streaming create acknowledgement
and research create acknowledgement, terminal wait and local validation. Logs
contain only approved phase/status labels and bounded elapsed milliseconds;
no IDs, preferences, prompt, result, URLs or raw exception content. Logging runs
after durable acknowledgement for create IDs and cannot throw into paid-work
control flow.

## User-facing timing
Prefer elapsed time, current phase and accepted day count. Do not show a fake
countdown, promise completion, or claim continued background execution without
confirmed active server work. The three observations can be described as roughly
3–4 minutes per three-day section only with their limited-sample caveat; they do
not establish an ETA for a new request. Measure more normal, authorized traffic
before proposing a percentile-based estimate. A model-effort change needs a
separately authorized quality/latency evaluation, not an untested deployment.

## Request to remove section breaks
The visible itinerary can be one continuous dated day list without altering its
internal checkpoints. A single nine-day provider response is a different change:
`SectionSpec`, repository and SQLite admission currently reject batches over
three days; preview storage and public grounded snapshots likewise reject more
than three preview days. The provider final-text decoder permits 64 KiB, streaming
text 128 KiB, the output request 32,768 tokens, and each response has an eight-minute
deadline. These are upper bounds, not a prediction of nine-day output size.

A larger batch might amortize repeated request/reasoning overhead, but needs a
coordinated versioned contract/storage/preview change plus representative quality,
completeness, cost and timeout evaluation. It could also postpone durable acceptance
until all nine days validate and increase work lost on invalid/truncated output.
Offline guard tests establish that simply changing the request size is unsupported;
they cannot establish provider latency or equivalent generated quality. Keep the
continuous dated UI independent of this proposed backend experiment. No larger
batch, shortened descriptions, reduced research or model-effort change is enabled.
