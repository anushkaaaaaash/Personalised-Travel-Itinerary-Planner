# Fly-only generation policy

User requested less reasoning and a longer bounded wait. The model remains
`gpt-6-luna`; `reasoning.effort=xhigh` replaces max in synchronous, background
and optional disabled web-research adapters. Official supported values:
https://developers.openai.com/api/docs/models/gpt-6-luna

Deadlines are provider read 300s, service 315s, browser 330s and Fly proxy idle
360s. Connect remains 10s. There are no automatic provider retries or duplicate
submissions. Larger waits are not evidence that generation succeeds; the durable
background path remains disabled until its existing storage startup issue is
resolved. The proxy setting is documented at:
https://fly.io/docs/reference/configuration/#http_service-http_options-idle_timeout

Deploy must coordinate any runtime OPENAI_REASONING_EFFORT override to xhigh.
The strict provider guard rejects other values rather than silently changing
the requested policy. No new credentials, model calls or paid tests are needed
for these offline checks.

Fly is the sole configured app origin; old Vercel routing configurations and
allowed preview origin are removed. Legacy platform environment detection is
retained only as a fail-closed safeguard against reading local credential files
in a hosted process, not a deployment dependency. Production preview-artifact
guard now applies to any production build. Supabase signup has no custom redirect
parameter: its account Site URL must be set to the Fly origin by the authorized
account operator. Existing confirmation messages may retain their original URL;
new confirmation links must be verified separately without claiming signin from
health checks. Existing Vercel service deletion is a separate account operation.
