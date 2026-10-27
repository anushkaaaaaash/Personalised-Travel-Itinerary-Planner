# Owner recovery and reasoning selection

Local candidate following the Kyoto rejection report. The screenshot alone did
not reveal the HTTP status. A contemporaneous aggregate 429 metric is supporting
evidence, not request/user attribution. Source confirmed that one retained active
or paused plan prevents another plan for that owner; the prior client discarded
the reason and could lose its local recovery handle.

The SQLite deployment now has a read-only authenticated `/api/adaptive-plans/current`
lookup. It derives the owner from verified authentication, excludes expired and
terminal plans, and fails closed rather than choosing between corrupt duplicate
current rows. It never creates, retries, cancels or schedules provider work.
Distinct owner-conflict and shared-capacity errors preserve the difference between
an unfinished trip and a busy service. The UI offers explicit recovery choices;
a cancellation must be confirmed before the untouched new-trip draft is unlocked.
Ambiguous create identities still reconcile by request ID, not by adopting a
different plan. Saved itineraries remain separate owner-verified Supabase records;
temporary adaptive checkpoints are not silently called account-saved trips.

The requested adaptive reasoning setting is **high** (superseding medium). Luna's
full documented list is none, low, medium(default), high, xhigh, max:
https://developers.openai.com/api/docs/models/gpt-6-luna
The provider still receives real strict JSON Schema Structured Outputs. Useful
descriptions are retained: fit, duration and practical considerations, without
repetitive prose or invented current facts. High can take longer than low.

Live web research and route-provider validation are NOT activated by this change.
The existing offline web/evidence adapters remain disabled. Current prices,
hours, closures, availability and transfer times are not represented as verified.
Adding paid source research, routes and resumable day previews is a separately
reviewed feature and budget decision, not a hidden change in this recovery fix.
No paid benchmark, new credential or production mutation was used for local tests.
