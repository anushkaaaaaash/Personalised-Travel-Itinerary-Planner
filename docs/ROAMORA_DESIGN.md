# Roamora experience

Roamora is the proposed product identity: an original route/compass R mark,
editorial typography, warm paper surfaces and destination-inspired palettes.
The name is a creative product choice, not a claim of trademark/domain clearance.
All artwork is original SVG/CSS; there are no stock-photo dependencies, remote
fonts, flag downloads or new runtime dependencies.

## Destination themes

`frontend/src/themes/countryThemes.js` contains 60 distinct palettes. Coverage
includes every destination in UN Tourism's **provisional 2024** top-50 arrivals
table (November 2025 World Tourism Barometer, annex A-7), plus ten additional
countries. The table includes territories and mixed reporting series. Some data
are missing; this is not a definitive current ranking and the UI does not call
it one. A palette is neither a safety assessment nor a recommendation to travel.

Sources checked 27 October 2026:
- [UN Tourism market intelligence](https://www.untourism.int/market-intelligence)
- [November 2025 Barometer hosted by CzechTourism, annex A-7](https://cms.czechtourism.cz/cms/getmedia/9db51d67-8a8f-4731-86b9-16b079568886/2025-world-tourism-barometer-and-statistical-annex-november-2025.pdf)

The catalogue is a separate dynamic-import chunk, warmed during browser idle
with a short timeout fallback. Typing a destination before warmup requests it
immediately. A failed load leaves a usable neutral theme. Country names and
curated city aliases resolve exactly after Unicode normalization, not by loose
substring matching. Ambiguous qualified input such as `Paris, Texas` stays
neutral; adding a supported country gives predictable matching. No destination
or theme preference is stored in the browser or sent to a separate service.
Saved-trip pages derive their palette from the loaded trip's preferences.

Global tokens update buttons, focus rings, backgrounds, cards, selections,
itinerary summaries, loading views, logo, illustration and mobile browser chrome.
Country palettes use abstract landscape motifs rather than national stereotypes.

## Accessibility and motion

- All 60 primary-button palettes exceed WCAG AA normal-text contrast (minimum
  approximately 6.32:1 for white text); theme text/background combinations are
  tested, including muted copy on tinted surfaces.
- Reduced-motion preference removes transitions and decorative motion. Existing
  loading-card pause/manual controls are preserved.
- Intro and page transitions are brief and finite, with no forced splash delay.
- Buttons have press feedback, visible keyboard focus and minimum 44px targets.
- Forms use 16px input text on mobile, responsive columns, error associations,
  keyboard-friendly native suggestions and focus movement between steps.
- A skip link bypasses destination inspiration. Print output removes ornamental
  navigation and keeps the itinerary readable.

## Email confirmation

`EmailConfirmation` is presentation for the independently verified callback
adapter. Checking, verified, unverified and unavailable states are distinct.
Success is shown only for the adapter's verified result, remains until Continue,
and does not silently sign the person in. Invalid/expired/already-used links are
not falsely called successful; connection failure is not falsely called expiry.
Continuing restores the sign-in form and its heading focus.

## Verification

Focused tests cover coverage, uniqueness, contrast, exact aliases, ambiguous
fallbacks, deferred loading, rapid destination changes, unmount cleanup,
confirmation states and explicit sign-in continuation. Existing journey tests
exercise loading, cancellation, generation, refinement and saved-trip behavior.
The visual-QA workflow uses a production build and synthetic intercepted API
responses on localhost only; it does not create accounts, send emails, call a
provider, write a database or publish a preview.
