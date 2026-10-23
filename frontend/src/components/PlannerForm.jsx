import { useEffect, useRef } from 'react';
import { PLANNER_STEPS, FINAL_STEP } from '../utils/plannerSteps.js';
import { CURRENCIES, INTEREST_OPTIONS } from '../../../shared/tripPreferences.mjs';

function PlannerForm({ form, onChange, onToggleInterest, onSubmit, onSave, onBack, onPreview, step = 0, loading, saved = false, errors = {} }) {
  const headingRef = useRef(null);
  const previousStep = useRef(step);
  useEffect(() => {
    if (previousStep.current !== step) {
      headingRef.current?.focus();
      previousStep.current = step;
    }
  }, [step]);
  const feedback = (name) => ({
    'aria-invalid': Boolean(errors[name]),
    'aria-describedby': errors[name] ? `${name}-error` : undefined,
  });
  const errorFor = (name) => errors[name] ? <span className="field-error" id={`${name}-error`}>{errors[name]}</span> : null;

  return (
    <form className="card planner-form" onSubmit={onSubmit} noValidate aria-busy={loading}>
      <div className="card__intro">
        <h2>Plan your trip</h2>
        <p>Capture your preferences. Saving does not generate an itinerary.</p>
      </div>

      <ol className="step-progress" aria-label="Planning progress">
        {PLANNER_STEPS.map((item, index) => (
          <li key={item.title} aria-current={index === step ? 'step' : undefined}>
            <span aria-hidden="true">{index + 1}</span>{item.title}
          </li>
        ))}
      </ol>
      <h3 ref={headingRef} tabIndex={-1} className="step-heading">Step {step + 1} of {PLANNER_STEPS.length}: {PLANNER_STEPS[step].title}</h3>
      {Object.keys(errors).length > 0 && <p role="alert" className="field-error">Please correct the highlighted preferences before continuing.</p>}
      <fieldset className="planner-fields" disabled={loading}>
        <legend className="sr-only">Trip preferences</legend>
        {step === 0 && <div className="form-grid">
          <label className="field">
            <span>Destination</span>
            <input name="destination" value={form.destination} onChange={onChange}
              placeholder="Kyoto, Japan" required maxLength={200} autoComplete="off" {...feedback('destination')} />
            {errorFor('destination')}
          </label>

          <label className="field">
            <span>Departure city</span>
            <input name="departureCity" value={form.departureCity} onChange={onChange}
              placeholder="Mumbai" required maxLength={200} autoComplete="off" {...feedback('departureCity')} />
            {errorFor('departureCity')}
          </label>

          <label className="field">
            <span>Start date</span>
            <input type="date" name="startDate" value={form.startDate} onChange={onChange}
              required {...feedback('startDate')} />
            {errorFor('startDate')}
          </label>

          <label className="field">
            <span>End date</span>
            <input type="date" name="endDate" value={form.endDate} onChange={onChange}
              min={form.startDate} required {...feedback('endDate')} />
            {errorFor('endDate')}
          </label>

        </div>}

        {step === 1 && <>
        <div className="form-grid">
          <label className="field">
            <span>Travelers</span>
            <input type="number" name="travelers" min="1" max="20" step="1"
              value={form.travelers} onChange={onChange} required {...feedback('travelers')} />
            {errorFor('travelers')}
          </label>

          <div className="field field--split">
            <label htmlFor="trip-budget">Budget</label>
            <div className="budget-row">
              <select name="currency" value={form.currency} onChange={onChange} aria-label="Currency" {...feedback('currency')}>
                {CURRENCIES.map((currency) => <option key={currency} value={currency}>{currency}</option>)}
              </select>
              <input id="trip-budget" type="number" name="budget" min="0" step="any"
                value={form.budget} onChange={onChange} placeholder="2500" required {...feedback('budget')} />
            </div>
            {errorFor('currency')}
            {errorFor('budget')}
          </div>
        </div>

        <fieldset className="interests" {...feedback('interests')}>
          <legend>Travel interests</legend>
          <div className="interest-pills">
            {INTEREST_OPTIONS.map((interest) => {
              const checked = form.interests.includes(interest.id);
              return (
                <label key={interest.id} className={`pill ${checked ? 'is-on' : ''}`}>
                  <input type="checkbox" checked={checked} onChange={() => onToggleInterest(interest.id)} />
                  {interest.label}
                </label>
              );
            })}
          </div>
          {errorFor('interests')}
        </fieldset>

        <div className="preference-options">
          <label className="field">
            <span>Dietary needs</span>
            <select name="dietaryNeeds" value={form.dietaryNeeds} onChange={onChange} {...feedback('dietaryNeeds')}>
              <option value="">No specific preference</option>
              <option value="vegetarian">Vegetarian</option>
              <option value="vegan">Vegan</option>
              <option value="jain">Jain</option>
              <option value="halal">Halal</option>
            </select>
            {errorFor('dietaryNeeds')}
          </label>
          <label className="field">
            <span>Travel pace</span>
            <select name="travelPace" value={form.travelPace} onChange={onChange} {...feedback('travelPace')}>
              <option value="relaxed">Relaxed</option>
              <option value="balanced">Balanced</option>
              <option value="fast">Fast-paced</option>
            </select>
            {errorFor('travelPace')}
          </label>
        </div>

        </>}
        {step === FINAL_STEP && <section className="trip-review" aria-label="Review your trip preferences">
          <dl>
            <dt>Destination</dt><dd>{form.destination}</dd>
            <dt>Departure city</dt><dd>{form.departureCity}</dd>
            <dt>Dates</dt><dd>{form.startDate} to {form.endDate}</dd>
            <dt>Travelers</dt><dd>{form.travelers}</dd>
            <dt>Budget</dt><dd>{form.currency} {form.budget}</dd>
            <dt>Interests</dt><dd>{form.interests.length ? form.interests.map((id) => INTEREST_OPTIONS.find((item) => item.id === id)?.label || id).join(', ') : 'None selected'}</dd>
            <dt>Dietary needs</dt><dd>{form.dietaryNeeds || 'No specific preference'}</dd>
            <dt>Travel pace</dt><dd>{form.travelPace}</dd>
          </dl>
          <p className="hint">Use Back to edit. Saving stores these preferences only; it does not generate an itinerary.</p>
        </section>}
        <div className="step-actions">
          {step > 0 && <button className="back-btn" type="button" onClick={onBack} disabled={loading}>Back</button>}
          {step < FINAL_STEP && <button className="generate-btn" type="submit" disabled={loading}>Next: {PLANNER_STEPS[step + 1].title}</button>}
        </div>
        {step === FINAL_STEP && <>
        <button className="generate-btn" type="button" onClick={onSave} disabled={loading || saved}>
          {loading ? 'Saving preferences…' : saved ? 'Preferences saved' : 'Save trip preferences'}
        </button>
        <button className="preview-btn" type="button" onClick={onPreview} disabled={loading}>
          Show sample preview (does not save)
        </button>
        </>}
      </fieldset>
    </form>
  );
}

export default PlannerForm;
