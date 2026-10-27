# OpenAI-only migration

Recommendations, initial day plans, whole-trip refinements and single-day refinements
all use `gpt-6-luna`, `reasoning.effort=max`, and `https://api.openai.com/v1/responses`.
Groq and Gemini adapters are removed. An obsolete/unknown provider or unsupported
model/reasoning setting fails configuration; there is no fallback or automatic retry.

## Private configuration

Set these server-only values in the process environment or the existing gitignored
`backend/.env` local fallback (not the frontend):

```dotenv
AI_PROVIDER=openai
OPENAI_API_KEY=your-private-key
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=max
```

Process values override the local file, including explicit blank values. Hosted
production/staging never reads that file. `backend-python/.env.local` may instead
be explicitly loaded with uvicorn `--env-file`; auth still requires its own existing
public Supabase configuration. Do not put any secret in a `VITE_` variable.
The legacy Express backend is not the AI application; use FastAPI as in the README.
The Render YAML remains REVIEW_ONLY and has not been applied.

## Request and acceptance boundaries

The HTTPX adapter uses a fixed OpenAI HTTPS endpoint, no redirects, no environment
proxy inheritance and no retries. Responses requests use `store:false`, strict JSON
Schema under `text.format`, and a 32,768-token maximum inclusive of reasoning.
No tools are requested. Only one completed assistant output-text message is accepted;
refusals, unexpected output/tool types, incomplete responses, invalid/oversized bodies
and malformed JSON fail closed. Reasoning content is never exposed or logged.

Existing full local validation remains authoritative: dates, whole-group whole-trip
budget, pacing, activity durations/counts, fixed commitments, target-day preservation,
warning metadata and refinement feasibility are unchanged. Structured output is not
proof that prices, hours, accessibility or locations are accurate.

Timeouts: 180-second adapter read-inactivity limit, 10-second connect limit,
45-second write/pool limits, 190-second overall provider-call deadline at the service,
and 210-second frontend deadline across all AI flows. These are bounded waiting
policies, not promised completion times. The browser calls Render directly; its
request does not pass through a Vercel function. Render's documented HTTP request
limit accommodates this window.

Timeout diagnostics contain only fixed event/subtype/stage enums and bounded elapsed
milliseconds. They never contain exception text, prompts, output, keys or headers.
Transport failures are distinguished from an expired overall service deadline;
a timeout does not prove schema acceptance, provider completion or absence of charges.
Max reasoning can exceed these limits; a timeout is a failed/unconfirmed generation,
not permission to downgrade or retry. Stopping the browser wait does not confirm
that provider work or billing stopped. No automatic retry or background storage was
introduced. Live latency and successful completion still require separately authorized
acceptance testing.

- [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/)
- [Render HTTP request limits](https://render.com/docs/render-vs-vercel-comparison)

## Official compatibility evidence (2026-10-27)

- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna): exact model and `max` reasoning support.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs): Responses `text.format` and strict schema.
- [Reasoning](https://developers.openai.com/api/docs/guides/reasoning): output budget includes reasoning; initial guidance recommends at least 25,000 tokens. We use 32,768 rather than the earlier proposed 16,384; incomplete output is never accepted.

## Offline verification

```sh
python -m venv .venv
.venv/bin/python -m pip install -r backend-python/requirements.txt
npm ci --ignore-scripts
.venv/bin/python -m pytest -c backend-python/pytest.ini backend-python/tests
npm test
npm run build
```

Tests inject synthetic settings and mock transports, not developer credentials.
No provider request, database mutation, push, merge or deployment is part of this
verification. A real acceptance request needs separate authorization.
