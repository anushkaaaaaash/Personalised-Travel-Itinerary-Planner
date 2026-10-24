# Activity 5.2 — Share and export

The React application has a private `/itineraries/:tripID` detail route. Open it from **My saved full itineraries → View details and share**. The route uses the existing owner-scoped saved-itinerary API, not legacy preference history. A URL does not grant another person access. After refresh, sign in again on the same URL; sessions remain memory-only.

Detail loading is read-only. Update uses the same saved ID and expected revision. Conflicts retain local changes and require an explicit reload/review. Regenerate and refine are explicit AI actions; the previous plan remains until a validated replacement arrives. Neither action automatically saves. Route changes, logout and unmount invalidate old responses. Back/Forward loads the saved revision; save local edits before navigating.

Sharing options:

- **Copy compact summary / Download summary:** dates, activity titles/timings and estimated group budget. Dietary, mobility and activity notes are omitted. Activity titles can still reveal personal choices, so review before sharing. Clipboard failure offers visible text for manual copying.
- **Download itinerary JSON:** bounded, allowlisted nested fields with the existing import contract. Full notes and available preferences are included and labelled sensitive. Account IDs, sessions and unknown transport fields are excluded. The file does not grant storage access or prove a booking.
- **Print / save PDF:** an isolated compact-summary document, with escaped text and no account form, history or editing controls. PDF saving remains the browser's print-dialog action.

No public-link service, sharing table, permissions migration, account changes or database writes are introduced by navigation/export. Existing Activity 5.1 records and security configuration are unchanged. Generation/refinement model routing remains unchanged.

## Runtime and verification

Node 20 or newer is required by React Router 7.18.4 (tested locally with Node 24). The router release was selected after the older 6.x candidate produced two npm audit advisories. The final dependency audit reports zero vulnerabilities.

Automated coverage includes private API selection, unsigned/invalid access, masked access errors, revision conflicts retaining edits, explicit generation without autosave, stale response disposal/logout, portable export roundtrips and field filtering, clipboard denial, HTML escaping and print cleanup. Python regressions remain unchanged and pass.

Live browser checks are separate from controller/rendering tests. The available browser automation surface timed out during inspection; no live signed-in 5.2 browser pass is claimed. Final manual acceptance, if automation remains unavailable: open an existing saved itinerary via View details, confirm the same saved revision, download/import its JSON locally, copy the compact summary, and inspect Print / save PDF. Do not confirm Update or Regenerate merely to test exports. No new account, trip write or AI call is needed for this check.

This activity does not submit progress to SkillWallet. Repository updates alone do not establish that a separate learning platform has synchronized its activity status.
