# Travel Planner consumer journey

The existing product identity and authenticated routes are retained. The main journey is destination/preferences → planning → itinerary → optional save/share/refinement.

## Consumer UI and preserved legacy functionality

`App → AuthBoundary → PlannerRoutes` exposes `/` and private `/itineraries/:tripID` only. These routes do **not** import `RecommendationResults`, `TripHistory`, `ItineraryResults`, `CoordinateConfirmation`, `RouteSummary`, or `ImportItinerary`. Those components and their service/export contracts remain preserved for developer reuse; there is no consumer link or active admin/import route to them. `consumerCopyMounted.test.js` verifies the route import graph and rendered journey/sharing copy. Portable JSON metadata remains in the programmatic export helper; the consumer summary/print path uses separate travel-focused copy.

## Background planning

The existing `/api/auth/config` response must explicitly report `planning_jobs_enabled: true`. Missing, false, malformed or failed configuration cannot enable background planning, and production does not depend on a Vercel build-time flag. With that backend readiness capability and an authenticated session, `PlannerPage` uses `planningJobController` and the authenticated planning-jobs client. It submits once, polls actual states, resumes through server-owned context, reconciles uncertain submissions by read-only request-ID lookup, and confirms server cancellation. It never silently resubmits an uncertain create.

Only opaque owner/request/job identifiers are retained in session storage. Preferences, itineraries, credentials and evidence stay in memory or authenticated server context. Logout/owner changes invalidate handles and late responses. Capability-off behavior continues to use the existing generation endpoint. The Vite preview flag is local-development/test-only and cannot override the ordinary application route’s backend capability. This frontend integration does not activate the backend or authorize paid requests.

## Practical checks

Verified assessments enter through a separately validated, digest-bound server evidence envelope. Activity-authored evidence is ignored. Checks are scoped to destination, stop, date and timezone; expiry downgrades them. Local edits and replacement refinements clear the envelope. Saved/imported/exported plans do not acquire verified status from embedded fields. Without evidence, opening hours, tickets, travel time and disruptions remain explicitly unchecked.

## Verification limit

Offline transport/controller/mounted tests and production builds pass. No real provider calls, database changes, publication, browser screenshots or visual acceptance were performed. The existing browser-access restrictions still require a supported connected browser or an authorized preview before visual release approval.
