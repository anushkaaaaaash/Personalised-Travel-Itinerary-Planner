# Epics 3 and 4 completion evidence

| Activity | Implementation and evidence |
| --- | --- |
| 3.1 | Preference capture/validation and existing Supabase preference persistence live verified; registration/login/JWT schemas validated. Production ownership/auth activation remains outside scope. |
| 3.2 | Dynamic prompt incorporates destination, dates, budget, travelers, interests, pace, style and practical needs. |
| 3.3 | Categorized AI recommendations, FastAPI routes and trip preference history verified. |
| 4.1 | Async provider abstraction, daily timelines, activity timings/notes and editing verified. |
| 4.2 | Synthetic feasible route reordered 1,2,3 to 1,3,2; estimated distance reduced 3.34km to 2.22km. Real estimates require explicitly confirmed coordinates; this is not live directions. |
| 4.3 | Vibes and whole/day feedback preserve constraints. One bounded live120b whole-trip refinement passed with three days and main counts [2,2,2]. Single-day preservation and ordinary endpoint model routing verified offline. |

Final pre-publication application checks: 514 Python tests, 287 JavaScript tests,
and Vite production build passed. The normal refinement endpoint selects120b;
generation and recommendations keep configured20b. Same4096 completion-token cap,
strict validation and no automatic retries. The failed20b capped-refinement path
is not claimed repaired; it is intentionally superseded for refinement.

AI prose is labeled unverified and separated from computed constraints. The accepted
sample had an inaccurate duration claim, demonstrating why structural validation
is not a guarantee of all narrative facts. No personal itinerary exports, live
credentials, logs, virtual environments or local acceptance fixtures are published.
Auth/migration/deployment review files do not imply those actions were executed.

The integration branch retains the existing main history and the earlier unpushed
Activity3.1 commit754ebd0. Neither original local working copy is overwritten.
