import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { createInitialForm } from '../src/utils/tripPreferences.js';
import { buildPreviewItinerary } from '../src/utils/buildPreviewItinerary.js';
import { plan as sharePlan } from './shareFixture.js';
import { detailRefinementState } from '../src/services/savedTripDetail.js';

let server;
let PlannerPage;
let RecommendationResults;
let PlannerForm;
let ItineraryResults;
before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    logLevel: 'silent',
    server: { middlewareMode: true, watch: null, hmr: false },
  });
  ({ default: RecommendationResults } = await server.ssrLoadModule('/src/components/RecommendationResults.jsx'));
  ({ default: PlannerPage } = await server.ssrLoadModule('/src/pages/PlannerPage.jsx'));
  ({ default: PlannerForm } = await server.ssrLoadModule('/src/components/PlannerForm.jsx'));
  ({ default: ItineraryResults } = await server.ssrLoadModule('/src/components/ItineraryResults.jsx'));
});
after(async () => { await server?.close(); });
const render = (component, props = {}) => renderToStaticMarkup(React.createElement(component, props));
const formHandlers = { onChange() {}, onToggleInterest() {}, onSubmit() {}, onSave() {}, onBack() {}, onPreview() {} };

test('pending storage disables refinement without exposing AI cancellation',async()=>{
  const {default: Controls}=await server.ssrLoadModule('/src/components/RefinementControls.jsx');
  const html=render(Controls,{result:sharePlan(),state:detailRefinementState({busy:true,activeAction:'update'}),onCancel(){},onRefine(){}});
  assert.ok(html.includes('Saving revision.'));assert.ok(html.includes('disabled=""'));assert.ok(!html.includes('Cancel regeneration'));
  const ai=render(Controls,{result:sharePlan(),state:detailRefinementState({busy:true,activeAction:'refine'}),onCancel(){},onRefine(){}});
  assert.ok(ai.includes('Cancel regeneration'));assert.ok(ai.includes('disabled=""'));
});

test('detail URLs require sign-in even in local mode and keep a return path', async () => {
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom');
  const { default: PlannerRoutes } = await server.ssrLoadModule('/src/components/PlannerRoutes.jsx');
  const html=renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:['/itineraries/32345678-1234-1234-1234-123456789abc']},React.createElement(PlannerRoutes,{signedIn:false,ownershipEnabled:false})));
  assert.ok(html.includes('Sign in to open your saved itinerary'));
  assert.ok(html.includes('stays selected after sign-in'));
  assert.ok(!html.includes('Regenerate local plan'));
});

test('router matches private detail parameters and unknown pages',async()=>{
  const { MemoryRouter } = await server.ssrLoadModule('react-router-dom');
  const { default: PlannerRoutes } = await server.ssrLoadModule('/src/components/PlannerRoutes.jsx');
  const renderPath=path=>renderToStaticMarkup(React.createElement(MemoryRouter,{initialEntries:[path]},React.createElement(PlannerRoutes,{signedIn:true,ownershipEnabled:false})));
  assert.ok(renderPath('/itineraries/32345678-1234-1234-1234-123456789abc').includes('Private saved itinerary'));
  assert.ok(renderPath('/not-a-route').includes('Page not found'));
});

test('initial page shows only first step, with no save or sample action', () => {
  const html = render(PlannerPage).match(/<form[\s\S]*?<\/form>/)[0];
  assert.ok(html.includes('Step 1 of 3: Trip details'));
  assert.ok(html.includes('name="destination"'));
  assert.ok(!html.includes('name="budget"'));
  assert.ok(!html.includes('>Save trip preferences<'));
  assert.ok(!html.includes('>Show sample preview'));
  assert.ok(html.includes('aria-current="step"'));
});

test('saved-only deployment hides legacy history and preference save while keeping full plans',()=>{
  const html=render(PlannerPage,{legacyEnabled:false,signedIn:true});
  assert.ok(!html.includes('Saved trip history'));assert.ok(html.includes('My saved full itineraries'));
  const review=render(PlannerForm,{...formHandlers,form:createInitialForm(),step:2,allowPreferenceSave:false});
  assert.ok(!review.includes('>Save trip preferences<'));assert.ok(review.includes('Generate AI day-by-day itinerary'));
});

test('preferences step retains controlled defaults and offers Back/Next only', () => {
  const html = render(PlannerForm, { ...formHandlers, form: createInitialForm(), step: 1 });
  assert.ok(html.includes('value="balanced" selected=""'));
  assert.ok(html.includes('value="" selected=""'));
  assert.ok(html.includes('>Back</button>'));
  assert.ok(html.includes('Next: Review &amp; save'));
  assert.ok(!html.includes('>Save trip preferences<'));
});

test('review renders all preferences and explicit non-submit save action', () => {
  const form = { ...createInitialForm(), destination: 'Kyoto', departureCity: 'Mumbai',
    startDate: '2028-02-28', endDate: '2028-02-29', dietaryNeeds: 'vegan' };
  const html = render(PlannerForm, { ...formHandlers, form, step: 2 });
  for (const value of ['Kyoto', 'Mumbai', '2028-02-28', '2028-02-29', 'USD', '2500', 'Culture, Food', 'vegan', 'balanced']) assert.ok(html.includes(value));
  assert.match(html, /class="generate-btn" type="button"/);
  assert.ok(!html.includes('type="submit"'));
  assert.ok(html.includes('Show sample preview (does not save)'));
  assert.ok(!html.includes('<input'));
});

test('saved review disables repeat saves while retaining navigation', () => {
  const html = render(PlannerForm, { ...formHandlers, form: createInitialForm(), step: 2, saved: true });
  assert.match(html, /disabled="">Preferences saved/);
  assert.ok(html.includes('>Back</button>'));
});

test('form validation is associated with its input for assistive technology', () => {
  const html = render(PlannerForm, { ...formHandlers, form: createInitialForm(), errors: { destination: 'Destination is required.' } });
  assert.match(html, /name="destination"[^>]*aria-invalid="true"[^>]*aria-describedby="destination-error"/);
  assert.ok(html.includes('id="destination-error">Destination is required.'));
});

test('in-flight form disables fields and exposes the saving status', () => {
  const html = render(PlannerForm, { ...formHandlers, form: createInitialForm(), step: 2, loading: true });
  assert.match(html, /<fieldset class="planner-fields" disabled=""/);
  assert.ok(html.includes('Saving preferences…'));
  assert.ok(html.includes('aria-busy="true"'));
});

test('loading/error result states cannot render a stale saved confirmation', () => {
  for (const props of [{ loading: true }, { error: 'Trip saving is not configured.' }]) {
    const html = render(ItineraryResults, { ...props, savedTrip: { id: 123 } });
    assert.ok(!html.includes('Trip preferences saved'));
    assert.ok(props.loading ? html.includes('aria-busy="true"') : html.includes('role="alert"'));
  }
});

test('sample preview declares limitations and cannot claim a saved trip on its own', () => {
  const itinerary = buildPreviewItinerary({
    ...createInitialForm(), destination: 'Kyoto', departureCity: 'Mumbai',
    startDate: '2027-02-10', endDate: '2027-02-12',
  });
  const html = render(ItineraryResults, { itinerary });
  assert.ok(html.includes('Sample preview · not generated or booked'));
  assert.ok(html.includes('Showing it does not save your trip'));
  assert.ok(!html.includes('Trip preferences saved'));
});

test('saved result shows confirmed ID and explicitly disclaims itinerary generation', () => {
  const html = render(ItineraryResults, { savedTrip: { id: 123 } });
  assert.ok(html.includes('Trip preferences saved'));
  assert.ok(html.includes('Confirmed trip ID: <strong>123</strong>'));
  assert.ok(html.includes('An itinerary has not been generated.'));
});

test('optional prompt controls and review show user preferences without inferring health details', () => {
  const form = { ...createInitialForm(), travelStyle: 'comfort', mobilityConcerns: 'Avoid stairs <script>' };
  const html = render(PlannerForm, { ...formHandlers, form, step: 1 });
  assert.ok(html.includes('Total budget (whole group, entire trip)'));
  assert.ok(html.includes('name="travelStyle"'));
  assert.ok(html.includes('value="comfort" selected=""'));
  assert.ok(html.includes('name="mobilityConcerns"'));
  assert.ok(html.includes('no medical details needed'));
  const review = render(PlannerForm, { ...formHandlers, form, step: 2 });
  assert.ok(review.includes('comfort'));
  assert.ok(review.includes('Avoid stairs &lt;script&gt;'));
  const empty = render(PlannerForm, { ...formHandlers, form: createInitialForm(), step: 2 });
  assert.ok(empty.includes('<dt>Mobility preferences</dt><dd>Not specified</dd>'));
});


test('AI action is separate from saving and respects both busy states', () => {
  const props = { ...formHandlers, form: createInitialForm(), step: 2 };
  const html = render(PlannerForm, { ...props, recommendationLoading: true });
  assert.match(html, /disabled="">Save trip preferences/);
  assert.match(html, /disabled="">Generating AI recommendations/);
  const saving = render(PlannerForm, { ...props, loading: true });
  assert.match(saving, /disabled="">Generate AI recommendations/);
});
test('AI cards label estimates, categories, and escape generated text', () => {
  const html = render(RecommendationResults, { result: { source: 'ai', destination: 'Goa', provider: 'test', model: 'fixture', currency: 'INR', warnings: ['Verify access'], recommendations: [{ id: 'a', category: 'dining', name: '<script>unsafe</script>', description: 'Restaurant', whyRecommended: 'Food', estimatedGroupCost: 200, interestTags: ['food'], travelStyle: '', dietaryNotes: '', mobilityNotes: '' }] } });
  assert.ok(html.includes('&lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(html.includes('Dining')); assert.ok(html.includes('not a trip total'));
  assert.ok(html.includes('Not verified')); assert.ok(html.includes('INR 200'));
});
test('AI loading and errors never show stale recommendations', () => {
  for (const props of [{ loading: true }, { error: 'AI not configured' }]) {
    const html = render(RecommendationResults, { ...props, result: { destination: 'stale' } });
    assert.ok(!html.includes('stale')); assert.ok(html.includes(props.loading ? 'role="status"' : 'role="alert"'));
  }
});


test('planner keeps all result panels grouped in one right-side grid column', () => {
  const html = render(PlannerPage);
  assert.match(html, /<\/form><div class="results-wrap" aria-label="Trip results">/);
  assert.match(html, /<\/div><\/main>/);
});

test('real AI itinerary displays days, budget warnings and local export without save claims', async () => {
  const { default: GeneratedItinerary } = await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');
  const result = { source: 'ai', saved: false, status: 'planned', destination: 'Kyoto <script>', provider: 'fixture', model: 'test', currency: 'USD', travelPace: 'balanced', explanation: 'Plan', warnings: ['Verify prices'], estimatedTotalGroupCost: 100, remainingBudget: 200, days: [{ date: '2028-01-01', mainActivityCount: 2, morning: '<img src=x>', afternoon: 'Garden', evening: 'Rest', dining: 'Dinner', transitAndRest: 'Breaks', dietaryNotes: 'Check menu', mobilityNotes: 'Check stairs', costs: { accommodation: 40, meals: 20, localTransport: 10, activities: 20, departureTravel: 10 } }] };
  const html = render(GeneratedItinerary, { result });
  for (const text of ['Planning copy · not booked', 'Day 1', 'Estimated whole-trip budget', 'USD 100', 'USD 200', 'Download itinerary JSON', 'Print / save PDF', 'Verify prices', '&lt;img src=x&gt;']) assert.ok(html.includes(text), text);
  assert.ok(!html.includes('Trip preferences saved'));
  const failed = render(GeneratedItinerary, { result, error: 'Not configured' });
  assert.ok(!failed.includes('Day 1')); assert.ok(failed.includes('Retry itinerary generation'));
  const infeasible = render(GeneratedItinerary, { result: { ...result, status: 'infeasible', days: [] } });
  assert.ok(infeasible.includes('No day plan was accepted')); assert.ok(!infeasible.includes('Download itinerary JSON'));
});
test('saved history labels legacy rows and explicit read-only prefill', async () => {
  const { default: TripHistory } = await server.ssrLoadModule('/src/components/TripHistory.jsx');
  const trip = { id: 12, destination: 'Kyoto', startDate: '2028-01-01', endDate: '2028-01-02', travelers: 2, preferencesStatus: 'unavailable', preferences: null };
  const html = render(TripHistory, { history: { result: { trips: [trip], offset: 0, hasMore: false } }, detail: { result: trip } });
  assert.ok(html.includes('not an authenticated personal account')); assert.ok(html.includes('Legacy preferences cannot be restored'));
  assert.ok(!html.includes('Use these preferences in planner'));
  const available = render(TripHistory, { history: {}, detail: { result: { ...trip, preferences: createInitialForm() } } });
  assert.ok(available.includes('Use these preferences in planner')); assert.ok(available.includes('It does not save or call AI'));
});
test('AI itinerary action remains separate and explicit on review', () => {
  const html = render(PlannerForm, { ...formHandlers, form: createInitialForm(), step: 2, itineraryLoading: true });
  assert.ok(html.includes('Generating AI day plan…')); assert.ok(html.includes('1–14 days'));
  assert.match(html, /disabled="">Save trip preferences/);
});
test('auth boundary fails closed until backend config is verified', async () => {
  const { default: AuthBoundary } = await server.ssrLoadModule('/src/components/AuthBoundary.jsx');
  const html = render(AuthBoundary);
  assert.ok(html.includes('Checking planner configuration')); assert.ok(!html.includes('Save trip preferences')); assert.ok(!html.includes('Saved trip history'));
});
test('JSON export creates a local file, includes non-booking notice and revokes blob URL', async () => {
  const { downloadItinerary } = await server.ssrLoadModule('/src/components/GeneratedItinerary.jsx');
  let blob, clicked = false, removed = false, revoked = false;
  const anchor = { click() { clicked = true; }, remove() { removed = true; } };
  downloadItinerary(sharePlan(), { createElement: () => anchor, body: { appendChild() {} } }, { createObjectURL(value) { blob = value; return 'blob:fixture'; }, revokeObjectURL(url) { assert.equal(url, 'blob:fixture'); revoked = true; } });
  assert.equal(anchor.download, 'travel-itinerary.json'); assert.equal(clicked, true); assert.equal(removed, true);
  const contents = JSON.parse(await blob.text()); assert.equal(contents.saved, false); assert.match(contents.notice, /not bookings/);
  await new Promise(r => setTimeout(r, 1050)); assert.equal(revoked, true);
});
test('refinement offers four vibes, conversational feedback and per-day target selection', async () => {
  const { default: RefinementControls } = await server.ssrLoadModule('/src/components/RefinementControls.jsx');
  const html = render(RefinementControls, { result: { days: [{ date: '2028-01-01' }] }, state: { error: 'Provider unavailable' } });
  for (const value of ['RELAXED', 'ADVENTURE', 'LUXURY', 'BUDGET', 'Your feedback', 'Only 2028-01-01', 'Whole itinerary', 'Your previous plan is retained']) assert.ok(html.includes(value));
});
test('route results show schematic estimates and never label missing distances as zero', async () => {
  const { default: RouteSummary } = await server.ssrLoadModule('/src/components/RouteSummary.jsx');
  const html = render(RouteSummary, { state: { result: { routeSummary: { basis: 'Straight-line estimate', warnings: [], days: [{ date: '2028-01-01', status: 'limited', orderedStops: [], legs: [], beforeDistanceKm: null, afterDistanceKm: null, timingChanges: [], warnings: ['Missing coordinates'] }] } } } });
  assert.ok(html.includes('not a map, live directions')); assert.ok(html.includes('Unavailable')); assert.ok(!html.includes('0.00 km')); assert.ok(html.includes('Missing coordinates'));
});

test('every recommendation retains controlled verification guidance even with unsafe assurances and empty model warnings', () => {
  const guidance = 'Dietary suitability and accessibility have not been verified. Confirm relevant ingredients, food preparation and access arrangements directly with the venue before relying on these suggestions.';
  const items = ['attraction', 'activity', 'dining'].map((category, index) => ({
    id: String(index), category, name: 'Fixture venue', description: 'Test only', whyRecommended: 'Culture',
    estimatedGroupCost: 100, interestTags: ['culture'], travelStyle: '',
    dietaryNotes: 'suitable for all dietary needs; no allergens listed <script>unsafe</script>',
    mobilityNotes: 'all restaurants ground level accessible',
  }));
  const html = render(RecommendationResults, { result: {
    source: 'ai', destination: 'Fixture', provider: 'test-only', model: 'fixture', currency: 'USD', warnings: [], recommendations: items,
  } });
  assert.equal(html.split(guidance).length - 1, 3);
  assert.equal(html.split('AI-generated · unverified').length - 1, 3);
  assert.equal(html.split('Unverified AI dietary notes:').length - 1, 3);
  assert.equal(html.split('Unverified AI mobility notes:').length - 1, 3);
  assert.ok(html.includes('suitable for all dietary needs; no allergens listed &lt;script&gt;unsafe&lt;/script&gt;'));
  assert.ok(html.includes('all restaurants ground level accessible'));
  assert.ok(!html.includes('<script>'));
});
test('hard activity cap is an explicit control, distinct from free-text feedback and vibe', async () => {
  const { default: RefinementControls } = await server.ssrLoadModule('/src/components/RefinementControls.jsx');
  const html = render(RefinementControls, { result: { days: [] } });
  assert.ok(html.includes('Maximum main activities per day')); assert.ok(html.includes('Keep current'));
  for (const n of [1, 2, 3, 4]) assert.ok(html.includes(`value="${n}">${n}</option>`));
  assert.ok(html.includes('Free-text feedback and vibes guide suggestions but do not set a numeric limit'));
});
test('import UI says local data only with a bounded JSON file selection', async () => {
  const { default: ImportItinerary } = await server.ssrLoadModule('/src/components/ImportItinerary.jsx');
  const html = render(ImportItinerary);
  assert.ok(html.includes('No AI request or database save')); assert.ok(html.includes('maximum 128 KiB')); assert.ok(html.includes('type="file"'));
});
test('coordinate confirmation is per stop, unchecked, explicit and not a claim of geographic verification', async () => {
  const { default: CoordinateConfirmation } = await server.ssrLoadModule('/src/components/CoordinateConfirmation.jsx');
  const html = render(CoordinateConfirmation, { itinerary: { days: [{ date: '2028-01-01', activities: [{ id: 'museum', title: '<Museum>', latitude: -18.9, longitude: 72.8 }] }] }, confirmed: [] });
  assert.ok(html.includes('Latitude for &lt;Museum&gt;')); assert.ok(html.includes('Longitude for &lt;Museum&gt;'));
  assert.ok(html.includes('I checked this specific place on a trusted map')); assert.ok(html.includes('We do not geographically verify'));
  assert.ok(!html.includes('checked=""')); assert.ok(!html.includes('Confirm all'));
});
