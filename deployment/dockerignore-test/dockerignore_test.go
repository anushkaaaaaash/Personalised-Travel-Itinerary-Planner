package dockerignore_test

import (
 "os"
 "testing"
 "github.com/moby/patternmatcher"
 "github.com/moby/patternmatcher/ignorefile"
)

func TestDockerContextExcludesSyntheticSecretsAndUserData(t *testing.T) {
 f, err := os.Open("../../.dockerignore"); if err != nil { t.Fatal(err) }; defer f.Close()
 patterns, err := ignorefile.ReadAll(f); if err != nil { t.Fatal(err) }
 matcher, err := patternmatcher.New(patterns); if err != nil { t.Fatal(err) }
 for _, name := range []string{"Dockerfile", "backend-python/requirements.txt", "backend-python/app/main.py", "backend-python/app/__init__.py", "frontend/src/App.jsx", "frontend/src/themes/countryThemes.js", "frontend/src/themes/DestinationTheme.jsx", "frontend/src/themes/roamora.css", "frontend/public/roamora.svg", "frontend/src/services/api.js", "frontend/src/index.css", "package-lock.json", "shared/tripPreferences.mjs", "frontend/tools/qaPreviewGuard.mjs"} {
  excluded, err := matcher.MatchesOrParentMatches(name); if err != nil || excluded { t.Fatalf("required source excluded: %s", name) }
 }
 for _, name := range []string{".env", "backend/.env", "backend-python/.env", "backend-python/.env.local", "backend-python/app/.env", "backend-python/app/.env.py", "backend-python/app/key.pem", "backend-python/app/fake.py/private.env", "backend-python/app/user-trip.json", "backend-python/app/__pycache__/main.pyc", "backend-python/tests/fixture.json", "backend-python/private/data.json", ".git/config", "frontend/.env", "frontend/src/themes/.env.js", "frontend/src/themes/key.pem", "frontend/src/themes/fake.js/private.env", "frontend/public/.env", "frontend/public/user-data.svg", "frontend/public/roamora.svg/private.env", "frontend/src/.env", "frontend/src/services/key.pem", "frontend/src/user-trip.json", "frontend/src/secret.js/private.env", "frontend/test/example.js", "frontend/public/__qa/index.html", "backend/server.js", ".venv/secrets", "fly.toml"} {
  excluded, err := matcher.MatchesOrParentMatches(name); if err != nil || !excluded { t.Fatalf("private/unneeded path included: %s", name) }
 }
}
