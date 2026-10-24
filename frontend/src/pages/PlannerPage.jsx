import { motion, useReducedMotion } from 'framer-motion';
import { useEffect, useRef, useState } from 'react';
import { FINAL_STEP, firstErrorStep, nextPlannerStep } from '../utils/plannerSteps.js';
import RecommendationResults from '../components/RecommendationResults.jsx';
import { getRecommendations } from '../services/recommendations.js';
import { createRecommendationRequest } from '../services/recommendationRequest.js';
import { optimizeItinerary } from '../services/routeOptimization.js';
import ImportItinerary from '../components/ImportItinerary.jsx';
import GeneratedItinerary from '../components/GeneratedItinerary.jsx';
import TripHistory from '../components/TripHistory.jsx';
import { createReadRequest } from '../services/readRequest.js';
import { generateItinerary, refineItinerary } from '../services/itineraries.js';
import { listTrips, getTrip } from '../services/tripHistory.js';
import SiteHeader from '../components/SiteHeader.jsx';
import PlannerForm from '../components/PlannerForm.jsx';
import ItineraryResults from '../components/ItineraryResults.jsx';
import { createTrip } from '../services/api.js';
import { createTripSubmission } from '../services/tripSubmission.js';
import { buildPreviewItinerary } from '../utils/buildPreviewItinerary.js';
import { buildTripPayload, createInitialForm } from '../utils/tripPreferences.js';

function PlannerPage({ ownershipEnabled = false }) {
  const reducedMotion = useReducedMotion();
  const [confirmedCoordinates, setConfirmedCoordinates] = useState([]);
  const [imported, setImported] = useState(null);
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(createInitialForm);
  const [submission, setSubmission] = useState({ loading: false, error: '', savedTrip: null });
  const [fieldErrors, setFieldErrors] = useState({});
  const [itinerary, setItinerary] = useState(null);
  const submissionRef = useRef(null);
  const recommendationsRef = useRef(null);
  const [recommendations, setRecommendations] = useState({ loading: false, error: '', result: null });

  const generationRef = useRef(null);
  const refinementRef = useRef(null);
  const optimizationRef = useRef(null);
  const [optimization, setOptimization] = useState({ loading: false, error: '', result: null });
  const [refinement, setRefinement] = useState({ loading: false, error: '', result: null });
  const [edited, setEdited] = useState(false);
  const historyRef = useRef(null);
  const detailRef = useRef(null);
  const emptyRead = { loading: false, error: '', result: null };
  const [generation, setGeneration] = useState(emptyRead);
  const [history, setHistory] = useState(emptyRead);
  const [detail, setDetail] = useState(emptyRead);
  const [prefilledId, setPrefilledId] = useState(null);

  useEffect(() => {
    const controller = createTripSubmission({ saveTrip: createTrip, onStateChange: setSubmission });
    submissionRef.current = controller;
    const recommendationController = createRecommendationRequest({ generate: getRecommendations, onStateChange: setRecommendations });
    recommendationsRef.current = recommendationController;
    optimizationRef.current = createReadRequest({ request: optimizeItinerary, onStateChange: setOptimization });
    refinementRef.current = createReadRequest({ request: refineItinerary, onStateChange: setRefinement });
    generationRef.current = createReadRequest({ request: generateItinerary, onStateChange: setGeneration });
    historyRef.current = createReadRequest({ request: listTrips, onStateChange: setHistory });
    detailRef.current = createReadRequest({ request: getTrip, onStateChange: setDetail });
    return () => {
      optimizationRef.current?.dispose();
      refinementRef.current?.dispose();
      generationRef.current?.dispose();
      historyRef.current?.dispose();
      detailRef.current?.dispose();
      controller.dispose();
      recommendationController.dispose();
      recommendationsRef.current = null;
      submissionRef.current = null;
    };
  }, []);

  function clearPreviousResult() {
    setConfirmedCoordinates([]);
    setImported(null);
    submissionRef.current?.reset();
    recommendationsRef.current?.reset();
    optimizationRef.current?.reset();
    refinementRef.current?.reset();
    setEdited(false);
    generationRef.current?.reset();
    detailRef.current?.reset();
    setPrefilledId(null);
    setFieldErrors({});
    setItinerary(null);
  }

  function handleChange(event) {
    if (submissionRef.current?.isBusy()) return;
    const { name, value } = event.target;
    const keepImport = imported?.missingPreferences && ['departureCity', 'travelers', 'dietaryNeeds', 'mobilityConcerns'].includes(name) ? { result: generation.result, info: imported } : null;
    clearPreviousResult();
    if (keepImport) { setGeneration({ loading: false, error: '', result: keepImport.result }); setImported(keepImport.info); }
    setForm((current) => ({ ...current, [name]: value }));
  }

  function handleToggleInterest(id) {
    if (submissionRef.current?.isBusy()) return;
    const keepImport = imported?.missingPreferences ? { result: generation.result, info: imported } : null;
    clearPreviousResult();
    if (keepImport) { setGeneration({ loading: false, error: '', result: keepImport.result }); setImported(keepImport.info); }
    setForm((current) => ({
      ...current,
      interests: current.interests.includes(id)
        ? current.interests.filter((item) => item !== id)
        : [...current.interests, id],
    }));
  }

  function validatedPayload() {
    const validation = buildTripPayload(form);
    setFieldErrors(validation.valid ? {} : validation.errors);
    if (!validation.valid) setStep(firstErrorStep(validation.errors));
    return validation.valid ? validation.value : null;
  }

  function handleSubmit(event) {
    event.preventDefault();
    // Enter advances earlier steps but can never write to the database.
    if (submissionRef.current?.isBusy() || step === FINAL_STEP) return;
    const next = nextPlannerStep(form, step);
    setFieldErrors(next.errors);
    setStep(next.step);
  }

  function handleBack() {
    if (submissionRef.current?.isBusy()) return;
    setFieldErrors({});
    setStep((current) => Math.max(0, current - 1));
  }

  function handleSave() {
    if (generationRef.current?.isBusy() || recommendationsRef.current?.isBusy() || step !== FINAL_STEP || submission.loading || submission.savedTrip || submissionRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (!payload) return;
    void submissionRef.current?.submit(payload);
  }

  function handleGenerateRecommendations() {
    if (generationRef.current?.isBusy() || step !== FINAL_STEP || submissionRef.current?.isBusy() || recommendationsRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (payload) void recommendationsRef.current?.submit(payload);
  }

  function handleGenerateItinerary() {
    if (step !== FINAL_STEP || submissionRef.current?.isBusy() || recommendationsRef.current?.isBusy() || generationRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (payload) { setConfirmedCoordinates([]); optimizationRef.current?.reset(); refinementRef.current?.reset(); setEdited(false); setItinerary(null); void generationRef.current?.submit(payload); }
  }

  async function handleRefine({ feedback, vibe, targetDate, maxMainActivitiesPerDay }) {
    if (submissionRef.current?.isBusy() || generationRef.current?.isBusy() || refinementRef.current?.isBusy()) return;
    const preferences = validatedPayload();
    if (!preferences || !generation.result) return;
    optimizationRef.current?.reset();
    setConfirmedCoordinates([]);
    const outcome = await refinementRef.current?.submit({ preferences, previous: generation.result, feedback, vibe, targetDate, maxMainActivitiesPerDay });
    if (outcome?.result) { setGeneration({ loading: false, error: '', result: outcome.result }); setEdited(false); }
  }

  function handleEditDay(day) {
    setConfirmedCoordinates([]);
    optimizationRef.current?.reset();
    refinementRef.current?.reset();
    setEdited(true);
    setGeneration(current => ({ ...current, result: { ...current.result, refinementSummary: null, days: current.result.days.map(d => d.date === day.date ? day : d) } }));
  }

  async function handleOptimize() {
    if (optimizationRef.current?.isBusy() || refinementRef.current?.isBusy() || generationRef.current?.isBusy()) return;
    const preferences = validatedPayload();
    if (!preferences || !generation.result) return;
    const outcome = await optimizationRef.current?.submit({ preferences, itinerary: generation.result, confirmedCoordinates });
    if (outcome?.result) { setGeneration({ loading: false, error: '', result: outcome.result.itinerary }); setEdited(true); }
  }

  function handleImport(data) {
    if (submissionRef.current?.isBusy()) return;
    clearPreviousResult();
    setForm(data.preferences || { ...createInitialForm(), ...data.knownPreferences, departureCity: '', travelers: '', interests: [], dietaryNeeds: '', mobilityConcerns: '' });
    setGeneration({ loading: false, error: '', result: data.itinerary });
    setEdited(data.userEdited);
    setImported({ missingPreferences: !data.preferences });
    setStep(data.preferences ? FINAL_STEP : 0);
  }

  function handleHistory(offset) {
    if (submissionRef.current?.isBusy()) return;
    detailRef.current?.reset();
    void historyRef.current?.submit({ offset, ownershipEnabled });
  }

  function handlePrefill(trip) {
    if (submissionRef.current?.isBusy() || !trip.preferences) return;
    clearPreviousResult();
    setForm({ ...createInitialForm(), ...trip.preferences, interests: [...trip.preferences.interests] });
    setStep(FINAL_STEP);
    setPrefilledId(trip.id);
  }

  function handlePreview() {
    if (step !== FINAL_STEP || submissionRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (payload) {
      if (submission.error) submissionRef.current?.reset();
      refinementRef.current?.reset();
      optimizationRef.current?.reset();
      setEdited(false);
      generationRef.current?.reset();
      setItinerary(buildPreviewItinerary(payload));
    }
  }

  return (
    <motion.div className="page" initial={reducedMotion ? false : { opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: reducedMotion ? 0 : 0.2 }}>
      <SiteHeader />
      <main className="layout">
        <PlannerForm
          form={form}
          onChange={handleChange}
          onToggleInterest={handleToggleInterest}
          step={step}
          onSubmit={handleSubmit}
          onSave={handleSave}
          onBack={handleBack}
          onPreview={handlePreview}
          onRecommendations={handleGenerateRecommendations}
          recommendationLoading={recommendations.loading}
          onGenerateItinerary={handleGenerateItinerary}
          itineraryLoading={generation.loading}
          loading={submission.loading}
          saved={Boolean(submission.savedTrip)}
          errors={fieldErrors}
        />
        <div className="results-wrap" aria-label="Trip results">
        {prefilledId !== null && <article className="card" role="status"><h2>Preferences loaded for review</h2><p>Loaded from saved trip {prefilledId}. No new save or AI request was made. Saving creates a new trip record.</p></article>}
        <ImportItinerary key={`${JSON.stringify(form)}-${JSON.stringify(generation.result)}-${submission.loading}-${generation.loading}-${refinement.loading}-${optimization.loading}`} onImport={handleImport} disabled={submission.loading || generation.loading || refinement.loading || optimization.loading} />
        {imported && <article className="card" role="status"><h2>Itinerary restored locally</h2><p>No AI request or database save was made. {imported.missingPreferences ? 'This older export has no original departure city, traveler count, interests or dietary/mobility preferences. Review those fields before refining. Existing day counts are unchanged.' : 'Original preferences were restored for review.'}</p></article>}
        <GeneratedItinerary confirmedCoordinates={confirmedCoordinates} onConfirmCoordinate={(entry, checked) => { optimizationRef.current?.reset(); setConfirmedCoordinates(current => [...current.filter(c => !(c.date === entry.date && c.id === entry.id)), ...(checked ? [entry] : [])]); }} preferences={buildTripPayload(form).valid ? buildTripPayload(form).value : null} {...generation} edited={edited} optimization={optimization} onOptimize={handleOptimize} onCancelOptimize={() => optimizationRef.current?.reset()} refinement={refinement} onEditDay={handleEditDay} onRefine={handleRefine} onCancelRefine={() => refinementRef.current?.reset()} onRetry={handleGenerateItinerary} onCancel={() => generationRef.current?.reset()} />
        <RecommendationResults {...recommendations} onRetry={handleGenerateRecommendations} onCancel={() => recommendationsRef.current?.reset()} />
        <ItineraryResults
          itinerary={itinerary}
          loading={submission.loading}
          error={Object.values(fieldErrors)[0] || submission.error}
          savedTrip={submission.savedTrip}
          generated={Boolean(generation.result)}
        />
        <TripHistory onCancelHistory={() => historyRef.current?.reset()} ownershipEnabled={ownershipEnabled} history={history} detail={detail} saving={submission.loading} onLoad={handleHistory} onSelect={(id) => { if (!submissionRef.current?.isBusy()) void detailRef.current?.submit(id); }} onPrefill={handlePrefill} onClose={() => detailRef.current?.reset()} onCancel={() => detailRef.current?.reset()} />
        </div>
      </main>
    </motion.div>
  );
}

export default PlannerPage;
