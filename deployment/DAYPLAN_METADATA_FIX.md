# Day-plan request metadata correction

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
value (`null`) to the unchanged public contract. It rejects a conflicting non-null
vibe. Existing explicit null remains compatible. No generated travel content is
filled, clipped or repaired. Refinement still uses its requested vibe and unchanged
schema. Recommendations, models, token cap, warnings and semantic validation are
unchanged. No automatic fallback or retry was added.

Regression coverage reconstructs the observed omission rather than pretending to
replay a retained provider body. Tests cover the outgoing schema and prompt,
unchanged public/refinement schema, conflicting values, infeasible output, missing
required content, timeline overlap and budget rejection. The earlier connected
offline React/FastAPI test remains separate, unpublished investigation work.

The single real request failed before this correction. Corrected live generation
is not yet verified. Do not interpret mocked acceptance as live success or deploy
this draft without review and approval. A later authorized verification must be
bounded, stop on failure/rate limits and avoid repeated requests. Public deployment,
authentication, credentials, CORS, billing and existing data were not changed.
