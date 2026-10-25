# Generation duration contract

The production diagnostic identified `less_than_equal` failures at
`days[0].activities[6].durationMinutes` and `days[1].activities[6].durationMinutes`.
This proves durations exceeded 240 minutes; it does not identify the activity or
its actual duration.

The public Pydantic model requires integer durations from 15 through 240. Groq's
private schema projection previously removed minimum/maximum keywords, leaving
only prose to communicate these limits. The projection now encodes this exact
finite domain using an integer enum. Groq documents integer and enum support:
https://console.groq.com/docs/structured-outputs

This applies to the Groq wire contract, including its derived private refinement
activity definition. The public schema and other providers are unchanged. Local
validation remains authoritative: invalid provider output is rejected without
clipping, repairing, retrying, or saving it. Models and the 4096 completion-token
cap remain unchanged.

Offline regressions inspect serialized requests, projection idempotence and
immutability, valid boundary values, rejection of out-of-range/non-integer mocked
responses, and private refinement propagation. These establish the submitted
contract, not live provider quality or successful production generation. No live
AI call was made for this fix; deployment and bounded acceptance remain pending.
