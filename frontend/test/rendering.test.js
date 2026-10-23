import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { createInitialForm } from '../src/utils/tripPreferences.js';
import { buildPreviewItinerary } from '../src/utils/buildPreviewItinerary.js';

let server;
let PlannerPage;
let PlannerForm;
let ItineraryResults;
before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    logLevel: 'silent',
    server: { middlewareMode: true, watch: null, hmr: false },
  });
  ({ default: PlannerPage } = await server.ssrLoadModule('/src/pages/PlannerPage.jsx'));
  ({ default: PlannerForm } = await server.ssrLoadModule('/src/components/PlannerForm.jsx'));
  ({ default: ItineraryResults } = await server.ssrLoadModule('/src/components/ItineraryResults.jsx'));
});
after(async () => { await server?.close(); });
const render = (component, props = {}) => renderToStaticMarkup(React.createElement(component, props));
const formHandlers = { onChange() {}, onToggleInterest() {}, onSubmit() {}, onSave() {}, onBack() {}, onPreview() {} };

test('initial page shows only first step, with no save or sample action', () => {
  const html = render(PlannerPage).match(/<form[\s\S]*?<\/form>/)[0];
  assert.ok(html.includes('Step 1 of 3: Trip details'));
  assert.ok(html.includes('name="destination"'));
  assert.ok(!html.includes('name="budget"'));
  assert.ok(!html.includes('>Save trip preferences<'));
  assert.ok(!html.includes('>Show sample preview'));
  assert.ok(html.includes('aria-current="step"'));
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
