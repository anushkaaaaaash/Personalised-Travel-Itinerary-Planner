# Day-plan generation contract correction — draft, not deployed

One explicitly authorized local request used synthetic six-day Jaipur preferences,
the existing Groq configuration, GPT-OSS-20B, strict schema and the unchanged 4096
token cap. There were no retries or database operations. Account plan was unknown.

The actual response was HTTP 400 (14,683 bytes). Its failed-generation JSON was
parsed in memory and compared against the exact outgoing schema. The required
root property `vibe` was absent. Raw provider content, keys and headers were not
persisted. This identifies one concrete failure; it does not establish the causes
of every historical HTTP 400 or the separate rate limit.

Ordinary generation requests no refinement vibe. The private generation schema
now omits this server-owned metadata, and the adapter supplies the known unset
value (`null`) to the unchanged public contract. The new private generation shape
does not accept model-selected metadata. No generated travel content is filled,
clipped or repaired. Refinement still uses its requested vibe and unchanged schema.
Recommendations, models, token cap and public semantic validation are unchanged.
No automatic fallback or retry was added.

Regression coverage reconstructs the observed omission rather than pretending to
replay a retained provider body. Tests cover the outgoing schema and prompt,
unchanged public/refinement schema, conflicting values, infeasible output, missing
required content, timeline overlap and budget rejection. The earlier connected
offline React/FastAPI test remains separate, unpublished investigation work.

## Subsequent real verification and retained failure evidence

One separately authorized verification returned HTTP 200 but a local capture
harness incorrectly preserved encoding headers after decoding. That attempt did
not establish application acceptance. The harness was repaired and independently
tested offline before another separately authorized verification.

That latest single request returned HTTP 200, finish_reason `stop`, and a real
six-day plan. Its 12,858 decoded bytes were retained in memory. FastAPI correctly
rejected three 30-minute overlaps and an empty final evening. Offline inspection
also established insufficient final-day main activities:

- Day 3: meal 08:00–09:00 overlaps main activity starting 08:30.
- Day 4: meal 07:30–08:30 overlaps transfer starting 08:00; main activity
  12:00–14:00 overlaps transfer starting 13:30.
- Day 6: blank evening; only meal and transfers, declared main count 1, actual
  main count 0. Balanced pace still requires 2–3 main activities on each day.

Safe fixture provenance: decoded response SHA256
`0ef4daf3d3f9fff880e889a5139b08a8c6246aa2f1855d91859a49fcb8eea062`.
Only numeric schedules, kinds, counts and blank-field evidence are reconstructed
in tests. Raw provider prose, credentials and personal data are not committed.
The real plan remains rejected; it was not silently repaired into success.

## Latest real acceptance and complete-contract review

The named-day/eight-slot contract subsequently received one separately authorized
request. Groq returned HTTP 400 with json_validate_failed. The 899 decoded bytes
were retained in memory and inspected before any further correction. SHA256:
`265cae505844aa8e719b171268b4c83305621b027dac04b7e54e32a65296f000`.
Its failed_generation was complete parseable JSON marked planned, containing only
explanation and warnings (verificationWarning plus empty additionalWarnings).
There was no days property or alternative itinerary structure. This is not visibly
cut-off JSON or an infeasible result. No token/finish metadata was supplied, so the
mechanism of the omission and any budget contribution remain unknown.

The committed captured-missing-days-shape fixture preserves this structure and
provenance, with prose explicitly replaced by synthetic strings. It is not a raw
provider-body replay. Both HTTP 400 and HTTP 200 carrying that malformed shape
remain rejected through the actual provider adapter and FastAPI route, without
retry or content fabrication.

Review found a separate concrete representation defect: alternating eight slots
cannot express breakfast then transfer then main activity, and fast pace leaves
no supporting slot after the last main. No prompt instruction requested omission
of days, and this representation restriction is not proven to cause that omission.

## Coherent generation-only correction

Replace alternating slots with ordered day and activity arrays. Every day carries
its explicit requested date, all narratives, costs, tags, dayStart and activities.
The prompt and schema list the same complete fields, place days first, and require
all requested dates in order. Infeasible output requires days: [], never omission.
All activity orders are representable within the existing eight-activity limit.
Exact coverage, pace-specific main counts, nonblank narratives and other semantic
bounds are enforced locally, not assumed from provider decoding.

The model proposes a day start, ordered durations and nonnegative gaps. The server
computes times from that representation, derives counts and request metadata, and
adds the visible computed-timing disclosure. It never shifts an old absolute-time
schedule or invents an activity/narrative. Absolute-time and fixed-time entries
are rejected in this private generation shape. Typed generation preferences have
no fixed commitments; meaningful constraints that cannot fit require infeasible.
Refinement preserves its existing fixed-time contract unchanged.

Midnight overflow, absent dates, empty evening, missing or excessive main events,
invalid coordinates, duplicate IDs, budgets and all existing public semantic
checks remain enforced. Existing model safety notices are retained. Recommendations,
refinement, GPT-OSS-20B generation, 4096-token cap and no-retry behavior are unchanged.
The earlier invalid six-day response remains rejected; it was not repaired.

## Evidence and remaining limits

Offline regression covers the captured omissions, three actual overlaps, blank
evening and zero final-day main events, complete/infeasible shapes, all paces,
flexible supporting-event order, boundary durations/gaps, date order, duplicate
fields/IDs, warnings and midnight. A representative synthetic multi-day response
passes the actual Groq adapter, FastAPI validation/serialization and mounted React
component with dates, activities, times, narratives and warnings. This is explicitly
synthetic success, not acceptance of the captured invalid provider response.

Official [Groq structured-output documentation](https://console.groq.com/docs/structured-outputs)
supports strict mode, arrays and closed required objects for GPT-OSS. No evidence
establishes an unsupported feature or provider-internal cause here. Strict mode
is retained; switching to JSON mode would not ensure complete content. Simplifying
the representation removes a proven restriction but does not guarantee the provider
will stop omitting days. A fresh separately approved acceptance is still needed.
No further provider calls, production changes or deployments were made during this
correction. Keep PR14 draft and unmerged; PR10/11 and auth work are untouched.
