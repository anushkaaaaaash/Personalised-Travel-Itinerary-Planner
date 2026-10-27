import { validGroundedPolicy } from '../services/groundedPlanning.js';
import { useTheme } from '../themes/DestinationTheme.jsx';
import { useEffect, useRef } from 'react';
import { PLANNER_STEPS, FINAL_STEP } from '../utils/plannerSteps.js';
import { CURRENCIES, INTEREST_OPTIONS, isRealIsoDate } from '../../../shared/tripPreferences.mjs';

function PlannerForm({ allowPreferenceSave = true, form, onChange, onToggleInterest, onSubmit, onSave, onBack, onPreview, onRecommendations, recommendationLoading = false, onGenerateItinerary, itineraryLoading = false, step = 0, loading, saved = false, errors = {}, recovery = null, onDismissRecovery, adaptiveEnabled = false, adaptivePolicy = null }) {
  const { theme, countries } = useTheme();
  const headingRef = useRef(null);
  const recoveryRef = useRef(null);
  const previousStep = useRef(step);
  const policy = adaptivePolicy?.sectionDays === 3 && Number.isSafeInteger(adaptivePolicy.maxSubmissionsPerRun) && adaptivePolicy.maxSubmissionsPerRun >= 1 && adaptivePolicy.maxSubmissionsPerRun <= 12 ? adaptivePolicy : null;
  const grounded = Boolean(policy && validGroundedPolicy(policy));
  const totalDays = isRealIsoDate(form.startDate) && isRealIsoDate(form.endDate) && form.endDate >= form.startDate ? (Date.parse(`${form.endDate}T00:00:00Z`) - Date.parse(`${form.startDate}T00:00:00Z`)) / 86400000 + 1 : null;
  useEffect(() => {
    if (previousStep.current !== step) {
      headingRef.current?.focus();
      previousStep.current = step;
    }
  }, [step]);
  useEffect(() => { if (recovery) recoveryRef.current?.focus(); }, [recovery]);
  const recommendationsFor = name => recovery?.recommendations?.filter(item => item.field === name) || [];
  const suggestionFor = name => recommendationsFor(name).some(item=>item.suggestion);
  const feedback = (name, hint) => ({
    'aria-invalid': Boolean(errors[name] || (['VALIDATION_ERROR','SECTION_MONEY_INVALID'].includes(recovery?.code) && suggestionFor(name))),
    'data-recommended': Boolean(suggestionFor(name)) || undefined,
    'aria-describedby': [errors[name] ? `${name}-error` : '', suggestionFor(name) ? `${name}-recovery` : '', hint].filter(Boolean).join(' ') || undefined,
  });
  const errorFor = name => <>{errors[name] && <span className="field-error" id={`${name}-error`}>{errors[name]}</span>}{suggestionFor(name) && <small className="field-recommendation" id={`${name}-recovery`}>{recommendationsFor(name).map((item,index)=><span className="field-recommendation__item" key={index}><strong>Suggested adjustment: </strong>{item.suggestion}{item.reason&&<><br/><strong>Why: </strong>{item.reason}</>}</span>)}</small>}</>;

  return (
    <form className="card planner-form" onSubmit={onSubmit} noValidate aria-busy={loading}>
      <div className="card__intro">
        <p className="eyebrow">Your next chapter</p><h2>{step === 0 ? "Let’s go somewhere." : step === 1 ? "Make it feel like you." : "A good trip starts here."}</h2>
        <p>{step === 0 ? "Start with the place and the dates. We’ll bring the days together." : step === 1 ? "A few little details make a big difference." : "One last look, then let the planning begin."}</p>
      </div>

      <ol className="step-progress" aria-label="Planning progress">
        {PLANNER_STEPS.map((item, index) => (
          <li key={item.title} aria-current={index === step ? 'step' : undefined}>
            <span aria-hidden="true">{index + 1}</span>{item.title}
          </li>
        ))}
      </ol>
      <h3 ref={headingRef} tabIndex={-1} className="step-heading">Step {step + 1} of {PLANNER_STEPS.length}: {PLANNER_STEPS[step].title}</h3>
      {recovery && <section className="planning-recovery" ref={recoveryRef} tabIndex={-1} aria-label={recovery.recommendations?.length ? 'Recommended changes' : 'Why planning stopped'}><h4>{recovery.proposed ? 'Suggestions to review' : recovery.recommendations?.length ? 'Recommended changes' : 'Why planning stopped'}</h4><p>{recovery.message}</p>{recovery.proposed&&<p>These are planning suggestions, not verified prices or availability. Review them before deciding what to change.</p>}{onDismissRecovery && <button type="button" className="back-btn" onClick={onDismissRecovery}>Dismiss guidance</button>}</section>}
      {Object.keys(errors).length > 0 && <p role="alert" className="field-error">Please correct the highlighted preferences before continuing.</p>}
      <fieldset key={step} className="planner-fields" disabled={loading}>
        <legend className="sr-only">Trip preferences</legend>
        {step === 0 && <><div className="form-grid">
          <label className="field">
            <span>Destination</span>
            <input name="destination" value={form.destination} onChange={onChange}
              placeholder="City, country — e.g. Kyoto, Japan" list="destination-countries" required maxLength={200} autoComplete="off" {...feedback('destination')} />
            <datalist id="destination-countries">{countries.map(country => <option key={country.code} value={country.name}/>)}</datalist>
            <small className="destination-theme-note" aria-live="polite">{theme.code === 'WORLD' ? 'Include a country to bring its colours to your trip.' : `${theme.name} palette · ${theme.story}`}</small>
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
              required {...feedback('startDate', 'trip-length-hint')} />
            {errorFor('startDate')}
          </label>

          <label className="field">
            <span>End date</span>
            <input type="date" name="endDate" value={form.endDate} onChange={onChange}
              min={form.startDate} required {...feedback('endDate', 'trip-length-hint')} />
            {errorFor('endDate')}
          </label>

        </div><p className="hint" id="trip-length-hint">{adaptiveEnabled ? 'Choose your full trip dates. Longer trips are planned in small sections, with pauses for you to continue.' : 'Plan 1–14 days at a time, including your start and end dates.'}</p></>}

        {step === 1 && <>
        <div className="form-grid">
          <label className="field">
            <span>Travelers</span>
            <input type="number" name="travelers" min="1" max="20" step="1"
              value={form.travelers} onChange={onChange} required {...feedback('travelers')} />
            {errorFor('travelers')}
          </label>

          <div className="field field--split">
            <label htmlFor="trip-budget">Total budget (whole group, entire trip)</label>
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
          <label className="field">
            <span>Travel style (optional)</span>
            <select name="travelStyle" value={form.travelStyle ?? ''} onChange={onChange} {...feedback('travelStyle')}>
              <option value="">No specific preference</option>
              <option value="budget">Budget</option>
              <option value="comfort">Comfort</option>
              <option value="luxury">Luxury</option>
            </select>
            {errorFor('travelStyle')}
          </label>
          <label className="field">
            <span>Mobility preferences (optional)</span>
            <input name="mobilityConcerns" value={form.mobilityConcerns ?? ''} onChange={onChange}
              maxLength={500} placeholder="For example: avoid stairs" {...feedback('mobilityConcerns')} />
            <small>Share practical access preferences only; no medical details needed.</small>
            {errorFor('mobilityConcerns')}
          </label>
        </div>

        </>}
        {step === FINAL_STEP && <section className="trip-review" aria-label="Review your trip preferences">
          <dl>
            <dt>Destination</dt><dd>{form.destination}</dd>
            <dt>Departure city</dt><dd>{form.departureCity}</dd>
            <dt>Dates</dt><dd>{form.startDate} to {form.endDate}</dd>
            <dt>Travelers</dt><dd>{form.travelers}</dd>
            <dt>Total budget (whole group, entire trip)</dt><dd>{form.currency} {form.budget}</dd>
            <dt>Interests</dt><dd>{form.interests.length ? form.interests.map((id) => INTEREST_OPTIONS.find((item) => item.id === id)?.label || id).join(', ') : 'None selected'}</dd>
            <dt>Dietary needs</dt><dd>{form.dietaryNeeds || 'No specific preference'}</dd>
            <dt>Travel pace</dt><dd>{form.travelPace}</dd>
            <dt>Travel style</dt><dd>{form.travelStyle || 'No specific preference'}</dd>
            <dt>Mobility preferences</dt><dd>{form.mobilityConcerns || 'Not specified'}</dd>
          </dl>
          <p className="hint">Everything look right? You can go back to change any detail.</p>
          {adaptiveEnabled&&<aside className="planning-disclosure" aria-label="How this trip will be planned"><h4>How planning works</h4>{policy&&totalDays&&<p>Your {totalDays}-day trip starts with an estimated {Math.ceil(totalDays / policy.sectionDays)} {totalDays<=policy.sectionDays?'section':'sections'}, covering up to {policy.sectionDays} days each.</p>}{grounded&&<p>Research is requested only when planning needs outside information. It can add model requests and search/tool usage to the section estimate.</p>}<p>{policy?(grounded?`Starting this run allows up to ${policy.maxSubmissionsPerRun} model requests, including research and retries, plus up to ${policy.maxWebSearchCalls} search/tool requests. `:`Starting this plan allows up to ${policy.maxSubmissionsPerRun} section requests in this batch. Retries use this allowance too. `):'Planning runs in bounded batches. '}You decide whether to continue after the request allowance is reached; your dates stay unchanged.</p>{grounded&&<p className="hint">A research or section response can take up to {policy.responseDeadlineMinutes} minutes. Completed sections remain available while later work runs.{policy.provisionalDayPreviews&&' Complete draft days may appear sooner, marked provisional until the section passes its checks.'}</p>}<p className="hint">Planning can pause earlier for a budget review, conflicting preferences, a service problem or storage limits. Any proposed changes are yours to review—not automatic edits.</p></aside>}
        </section>}
        <div className="step-actions">
          {step > 0 && <button className="back-btn" type="button" onClick={onBack} disabled={loading}>Back</button>}
          {step < FINAL_STEP && <button className="generate-btn" type="submit" disabled={loading}>Next: {PLANNER_STEPS[step + 1].title}</button>}
        </div>
        {step === FINAL_STEP && <>
        <button className="generate-btn build-trip" type="button" onClick={onGenerateItinerary} disabled={loading || recommendationLoading || itineraryLoading}>
          {itineraryLoading ? 'Putting your trip together…' : 'Build my trip →'}
        </button>
        <p className="hint">A day-by-day plan shaped around your dates, interests and pace.</p>
        </>}
      </fieldset>
    </form>
  );
}

export default PlannerForm;
