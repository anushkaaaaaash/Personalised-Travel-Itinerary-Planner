import { useEffect, useRef, useState } from 'react';
import { FINAL_STEP, firstErrorStep, nextPlannerStep } from '../utils/plannerSteps.js';
import SiteHeader from '../components/SiteHeader.jsx';
import PlannerForm from '../components/PlannerForm.jsx';
import ItineraryResults from '../components/ItineraryResults.jsx';
import { createTrip } from '../services/api.js';
import { createTripSubmission } from '../services/tripSubmission.js';
import { buildPreviewItinerary } from '../utils/buildPreviewItinerary.js';
import { buildTripPayload, createInitialForm } from '../utils/tripPreferences.js';

function PlannerPage() {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState(createInitialForm);
  const [submission, setSubmission] = useState({ loading: false, error: '', savedTrip: null });
  const [fieldErrors, setFieldErrors] = useState({});
  const [itinerary, setItinerary] = useState(null);
  const submissionRef = useRef(null);

  useEffect(() => {
    const controller = createTripSubmission({ saveTrip: createTrip, onStateChange: setSubmission });
    submissionRef.current = controller;
    return () => {
      controller.dispose();
      submissionRef.current = null;
    };
  }, []);

  function clearPreviousResult() {
    submissionRef.current?.reset();
    setFieldErrors({});
    setItinerary(null);
  }

  function handleChange(event) {
    if (submissionRef.current?.isBusy()) return;
    const { name, value } = event.target;
    clearPreviousResult();
    setForm((current) => ({ ...current, [name]: value }));
  }

  function handleToggleInterest(id) {
    if (submissionRef.current?.isBusy()) return;
    clearPreviousResult();
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
    if (step !== FINAL_STEP || submission.loading || submission.savedTrip || submissionRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (!payload) return;
    void submissionRef.current?.submit(payload);
  }

  function handlePreview() {
    if (step !== FINAL_STEP || submissionRef.current?.isBusy()) return;
    const payload = validatedPayload();
    if (payload) {
      if (submission.error) submissionRef.current?.reset();
      setItinerary(buildPreviewItinerary(payload));
    }
  }

  return (
    <div className="page">
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
          loading={submission.loading}
          saved={Boolean(submission.savedTrip)}
          errors={fieldErrors}
        />
        <ItineraryResults
          itinerary={itinerary}
          loading={submission.loading}
          error={Object.values(fieldErrors)[0] || submission.error}
          savedTrip={submission.savedTrip}
        />
      </main>
    </div>
  );
}

export default PlannerPage;
