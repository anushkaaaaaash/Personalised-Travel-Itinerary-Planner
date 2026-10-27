# Temporary visual QA preview

These secret-free HTML snapshots render the actual React components and current index.css using synthetic data. No scripts, authentication, provider calls or API requests are included. The pages are noindex and have restrictive CSP. Use the same URLs at desktop (1440×1000) and mobile (390×844) viewport widths.

Start: `/__qa/index.html`
Screens: `discovery.html`, `preferences.html`, `review.html`, `loading.html`, `itinerary.html`, `error.html`.

Regenerate after component/CSS changes: `node frontend/tools/renderQaPreview.mjs` from repository root.

Before final main merge: remove this entire `frontend/public/__qa` directory and rerun tests and production build. The Vite guard rejects a Vercel production build while these artifacts remain. The source generator and guard may remain for future explicitly approved preview work.

Static screenshots verify layout only. Interactive behavior is covered separately by mounted tests and still needs supported-browser acceptance against the actual app.
