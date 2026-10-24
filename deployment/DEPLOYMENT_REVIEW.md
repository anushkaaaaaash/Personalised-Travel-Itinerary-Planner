# Superseded deployment review

Use [Activity 5.3 and 5.4 readiness and exact approval plan](ACTIVITY_5_3_5_4.md).

Do not apply the old legacy ownership migration or set its flags true for deployment.
Production now excludes legacy preference history and uses the existing saved_itineraries RLS boundary.
Templates remain review-only; no cloud resources, host secrets or deployment have been configured.
