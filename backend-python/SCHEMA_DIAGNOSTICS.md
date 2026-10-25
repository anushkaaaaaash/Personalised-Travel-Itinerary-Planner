# Provider schema diagnostics

The live `json_validate_failed` error reported required missing properties, but the previous sanitizer removed standalone quoted names and many real schema paths. This change improves evidence collection; it does not fix or prove successful live itinerary generation.

The adapter supplies the exact projected outgoing schema to the bounded error parser. Only property/definition names in that schema and fixed structural vocabulary may appear in paths. `missingProperties` contains at most eight distinct exact property names extracted beside explicit missing/required-property markers. Unknown identifiers, values, descriptions, enums, prompts and `failed_generation` bodies are never inspected for names or logged. Error bodies remain capped at 8192 bytes. A reported name means the provider mentioned it, not independent proof that it was absent.

The earlier error cannot be reconstructed from its sanitized log. No richer retained provider response is available through the current authorized access; Render browser automation is stopped. No live request is needed to test this parser. After review and deployment approval, one separately authorized bounded attempt may supply actionable evidence. Do not retry HTTP 400 or consume quota repeatedly.

## Offline output-shape assessment

The current generation wire schema has five closed object definitions, all fields required, and resolved local references. Planned and infeasible responses use the same root fields; infeasible results may have empty days but still require warnings. The required warning object is converted verbatim to the unchanged public warning array. No output-shape contradiction has been established from the available error.

A compact private representation or copying deterministic preference fields from validated input could reduce generated output, but would introduce adapter behavior and needs its own evidence and review. Flattening warnings would merely move the same required field; removing warnings or required fields would weaken the contract. No such speculative changes are included. Models, schema, prompts, token limits, retry behavior, public validation and storage remain unchanged.

Tests use synthetic messages and mocked HTTP only, including missing fields, nested paths, inactive/unknown identifiers, adversarial payloads, malformed/oversized errors, bounded inventory and a single provider invocation. No credentials, user records or raw provider payloads belong in this document or repository.
