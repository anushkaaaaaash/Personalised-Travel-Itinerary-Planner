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

## Prospective generation-only contract

Groq now proposes named day objects and eight ordered activity slots. Existing
pace determines mandatory main slots; optional main slots cannot exceed the upper
bound. Supporting slots accept only meal/rest/transfer/lodging kinds. The adapter
derives request metadata and actual main counts, never inventing missing content.

The model proposes a day start, durations and nonnegative gaps. Clock times are
computed in slot order, not corrected from an old absolute schedule. Accepted
entries therefore cannot overlap. A schedule exceeding midnight is rejected.
Absolute activity times and fixed-time fields are forbidden in this private
generation shape. The typed generation preferences contain no fixed commitments;
if meaningful external timing constraints cannot fit, the prompt requires an
infeasible response. Refinement preserves its fixed commitments unchanged.

Every daily narrative including evening is mandatory and locally checked for
nonblank text. Missing AI content is never filled with a generic placeholder.
Departure/rest-only days receive no new pace exemption: if the plan cannot meet
the existing rules, return infeasible with all day values null. Public validation
still checks text, coordinates, dates, budget, interests, pace, duplicate IDs and
the final timeline.

Planned results carry a separate visible warning identifying computed times as
unverified proposals, not bookings. Model-authored safety warnings are preserved;
at most six additional warnings leave room for this disclosure. Infeasible results
do not claim a computed schedule.

## Enforcement and limits

Required slots/kinds, duration/gap domains and day keys are structural constraints.
Nonblank prose and practical travel/venue feasibility are not guaranteed by provider
decoding; local validators still reject invalid content. Alternating slot types
bound the representation: not every eight-event sequence fits (four main entries
at fast pace leave no supporting slot after the final main). The model must choose
a coherent supported plan or report infeasible; no event is dropped by the adapter.

Offline coverage includes the observed failures, mixed supporting activities,
all paces, zero gaps, midnight, invalid durations/coordinates, reversed JSON key
order, required narratives/warnings and FastAPI serialization into mounted React.
Successful fixtures are synthetic, separate from the rejected captured response.

The new private contract has NOT received a live provider request. Public deployment,
authentication, credentials, CORS, billing and existing data were not changed.
Keep this PR unmerged. A separately authorized bounded verification must establish
actual provider acceptance and rendering before deployment; mocks are not live proof.
