# Required main activities: locally verified correction, not deployed

The latest actual six-day response returned HTTP 200 but was rejected at day 1's
PACE guard. Durable evidence hash:
`4c9da92aee894d03254d49b9d34f54b0445bf5c12d88f977dc4163980e1e83d9`.
There were three entries including accommodation. The other two kinds were not
retained, so the exact main count is unknown; it was necessarily zero or one.
The evidence fixture records those limits, not invented titles or full response
content. Tests reconstruct both possible failing counts with synthetic prose.

## Exact enforcement gap

Balanced pace has meant two to three main activities per day since the first
published FastAPI implementation (`19bc6b2`). Current generation instructions
explicitly include arrival and departure days. No arrival-day exemption or
prompt/validator contradiction was found. Available course text does not establish
that this numeric mapping is a course mandate; it is the existing product rule,
preserved under the user's instruction not to weaken validation.

Before this correction, the provider schema permitted an array containing only
supporting activities. The prompt instructed a minimum but the schema did not
enforce it; local semantic validation rejected the incomplete result afterward.
This is model noncompliance allowed by the private schema, not a parser failure.

## Local correction

Each generated day now has `requiredMainActivities`: one, two or three required
non-null full main proposals for relaxed, balanced or fast pace respectively.
Their `kind` must be `main`. An `activities` array holds additional entries,
including at most one additional main under existing local upper bounds.
Missing required experiences cannot pass structural validation. The adapter does
not generate descriptions, reclassify meals/transfers or repair the captured plan.

Every entry supplies an explicit `sequence` position across both containers.
Positions must be unique and consecutive. The adapter follows that proposed order
and the existing duration/gap scheduling contract; object key order does not set
the timeline. Breakfast, transfer and check-in can precede any main activity, and
supporting events can follow the last main. There are no alternating eight slots.
The combined eight-entry limit, all dates/narratives, public validators, budget,
coordinates, warnings, midnight rejection and computed-timing notice remain.
Working recommendations, refinement, model, token cap and retries are unchanged.

## Evidence and limits

Offline tests reject both possible captured under-counts at the required schema
fields, reject null/misclassified mains and ambiguous sequence positions, and
accept complete synthetic proposals through the actual FastAPI response and
mounted React component. All paces and flexible supporting-event order are tested.
The captured incomplete response remains rejected. A schema label cannot establish
real-world suitability or prevent a model from describing a meal as a main event;
prompt instructions against misclassification remain. Provider-side omission can
still produce a rejection; a single successful request is not a general reliability
or factual travel-accuracy guarantee.

## Separately authorized local real-provider acceptance

Exactly one Groq request used synthetic six-day preferences and the reviewed
correction. HTTP 200 returned all six requested days and 24 activities, including
the two required main proposals each day. Required narratives were nonblank.
The actual response passed private checks, public FastAPI validation and
serialization, then mounted React rendering with all 24 activities and seven
warnings. Schedule checks passed; displayed times retain the computed-timing
disclosure. There was one UI request and zero provider requests from the renderer;
offline replay did not call Groq. No automatic retry occurred.

Safe provenance: decoded response SHA256
`7597290f0730dec8f6f2718300e04779216167d490eb65ac8633639171d39a84`.
Tested generation_contract.py SHA256:
`21e6b526b1c880781776126a9f7a89037fed42a770fb5a6128e18fe6c4316e3b`.
Raw provider content, credentials and personal data are not committed. The local
atomic artifact retains redacted structure and safe diagnostics only.

753 Python tests, 359 JavaScript tests, the production build, public-asset scan,
18 local harness lifecycle/diagnostic tests and independent review passed. This
is local live-provider evidence, not a production website test. The published PR
must remain unmerged until approval. No production configuration, deployment,
recommendations, refinement, credentials, billing or user data were changed.
