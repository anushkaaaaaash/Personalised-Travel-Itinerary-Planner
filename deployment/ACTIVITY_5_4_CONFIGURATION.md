# Activity 5.4 configuration audit

This audit inspects source, templates and synthetic tests, not private environment
contents. It does not generate credentials, install providers or change hosts.

| Requirement | Implementation / evidence | Limit |
|---|---|---|
| Typed configuration | `app/configuration.py` uses Pydantic `ProviderSettings`, `Literal` provider/model validation and `SecretStr`; production startup validates auth, domains and provider before serving | Not a copied course `Settings` class; validation is shared with existing auth/security modules |
| Local precedence | Explicit uvicorn `--env-file backend-python/.env.local` loads process values; process values override legacy `backend/.env` fallback; fallback interpolation disabled | Existing process variables take precedence over dotenv; restart after operator changes |
| Staging/production | `APP_MODE=production`, `APP_ENV=staging` or `production`; no workstation fallback; exact origins/host and saved-schema attestation required | Staging behavior tested offline; no separate staging cloud resource created |
| AI configuration | Existing Groq key server-only; `GROQ_MODEL` defaults to 20B, `GROQ_REFINEMENT_MODEL` to 120B; invalid provider/model fails safely | No model or key switched by this audit |
| Supabase separation | Public key + verified JWT for user operations; explicit administrative factory separate; legacy privileged storage disabled when hosted | Actual private values not printed or reconfigured |
| Frontend separation | Only public `VITE_API_BASE_URL`; hosted URL validated, suspicious credential variable names rejected, bundle scanned | Pattern scans are not an absolute secret-free guarantee |
| Git hygiene | `.env` variants ignored, placeholder `.env.example` files tracked; CI rejects tracked private environment files | Never put real values in templates, logs, PRs or screenshots |
| JWT signing sample | Supabase Auth issues/signs sessions and verifies access tokens remotely | `SECRET_KEY`, `ALGORITHM`, local expiry settings are intentionally unused; generating them would not add security |
| Hugging Face / Ollama | Conditional alternative exercises documented | No adapter, token, installation, downloaded model or offline inference is claimed; obtain scope approval if assessment requires one |

## Operator configuration map

Use `backend-python/.env.example` for local placeholder names and
`render.REVIEW_ONLY.yaml` for hosted names. The review-only template is not an
instruction to create another service. Keep `TRIP_OWNERSHIP_ENABLED` and
`TRIP_OWNERSHIP_SCHEMA_VERIFIED` false: only the separate saved-itinerary table has
the verified owner policies. Set `SAVED_ITINERARIES_SCHEMA_VERIFIED` true only after
the actual schema/policy inspection; a flag does not perform verification.

For staging use separate approved project/configuration where isolation is needed;
never assume changing `APP_ENV` isolates database records. Configure keys directly
in the approved server environment UI, not in chat. Existing working Groq
credentials satisfy the Groq setup requirement; do not create a redundant key.
Gemini is a retained optional adapter, not the deployed provider or a substitute
claim for Hugging Face/Ollama.

Tests use mocked file readers and synthetic settings to verify hosted file
isolation, explicit blank-value precedence, public-key selection, redaction and
configuration rejection. No live AI calls or database mutations are needed.
This audit completes the current Groq/Supabase configuration path; optional
provider exercises and custom JWT signing are not represented as completed.
