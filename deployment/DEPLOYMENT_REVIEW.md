# Superseded deployment review

Use [Activity 5.3 and 5.4 readiness and exact approval plan](ACTIVITY_5_3_5_4.md).

Do not apply the old legacy ownership migration or set its flags true for deployment.
Production now excludes legacy preference history and uses the existing saved_itineraries RLS boundary.
Templates remain review-only. The existing course-demo services were configured by
the operator during Activity 5.3; do not recreate them. See
[Activity 6.1 existing-service readiness](ACTIVITY_6_1_RENDER.md) for the connected
Git provider, user-confirmed CI-gated setting and verification limits. No new
Git-provider approval is needed based on the supplied Settings evidence.
