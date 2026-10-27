> Historical checkpoint: provider setup below is superseded by [OpenAI-only setup](OPENAI_SETUP.md). Groq/Gemini adapters have been removed; do not configure their credentials. No deployment is authorized by this document.

# Activity 3.3 and supplied Epic 4 implementation

The consolidated update includes the provider interface, course-required Groq
adapter (default), optional Gemini adapter, recommendation cards, saved-trip
fetch/history, day-by-day itinerary generation, route/time optimization, timeline
editing, vibe selection and conversational full/day refinement. See the project
CONSOLIDATED_UPDATE.md and GROQ_SETUP.md for current setup and limitations.

All output is schema-validated before display; provider output is not proof of
factual prices, opening hours, geographic accuracy, diet safety or accessibility.
Route calculations are explicit estimates, not live routing/navigation.

Trip preferences are saved only by the explicit Save action. AI generation,
optimization and refinement do not silently overwrite existing saved preferences.
History lists saved preferences, not a durable log of all generated responses.

Auth/owned storage code is included, but database ownership migration and real
registration/login/RLS isolation require separate approval/setup and verification.
The default legacy mode remains private loopback-only with Host/Origin checks.
No user has been assigned ownership of legacy NULL-owner rows automatically.

This code update has not yet been applied to the user's Windows project or
verified with a live Groq request. Tests use synthetic providers/transports.
Public Vercel/Render deployment and any unprovided Epic 5–7 details remain pending.
