import { INTEREST_OPTIONS } from '../utils/buildPreviewItinerary.js';

function PlannerForm({ form, onChange, onToggleInterest, onSubmit, loading }) {
  return (
    <form className="card planner-form" onSubmit={onSubmit}>
      <div className="card__intro">
        <h2>Plan your trip</h2>
        <p>Share a few details and generate a tailored itinerary preview.</p>
      </div>

      <div className="form-grid">
        <label className="field">
          <span>Destination</span>
          <input
            name="destination"
            value={form.destination}
            onChange={onChange}
            placeholder="Kyoto, Japan"
            required
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span>Departure city</span>
          <input
            name="departureCity"
            value={form.departureCity}
            onChange={onChange}
            placeholder="Mumbai"
            required
            autoComplete="off"
          />
        </label>

        <label className="field">
          <span>Start date</span>
          <input
            type="date"
            name="startDate"
            value={form.startDate}
            onChange={onChange}
            required
          />
        </label>

        <label className="field">
          <span>End date</span>
          <input
            type="date"
            name="endDate"
            value={form.endDate}
            onChange={onChange}
            min={form.startDate}
            required
          />
        </label>

        <label className="field">
          <span>Travelers</span>
          <input
            type="number"
            name="travelers"
            min="1"
            max="20"
            value={form.travelers}
            onChange={onChange}
            required
          />
        </label>

        <div className="field field--split">
          <span>Budget</span>
          <div className="budget-row">
            <select name="currency" value={form.currency} onChange={onChange} aria-label="Currency">
              <option value="USD">USD</option>
              <option value="EUR">EUR</option>
              <option value="INR">INR</option>
            </select>
            <input
              type="number"
              name="budget"
              min="1"
              step="1"
              value={form.budget}
              onChange={onChange}
              placeholder="2500"
              required
            />
          </div>
        </div>
      </div>

      <fieldset className="interests">
        <legend>Travel interests</legend>
        <div className="interest-pills">
          {INTEREST_OPTIONS.map((interest) => {
            const checked = form.interests.includes(interest.id);
            return (
              <label key={interest.id} className={`pill ${checked ? 'is-on' : ''}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => onToggleInterest(interest.id)}
                />
                {interest.label}
              </label>
            );
          })}
        </div>
      </fieldset>

      <button className="generate-btn" type="submit" disabled={loading}>
        {loading ? 'Generating itinerary…' : 'Generate Itinerary'}
      </button>
    </form>
  );
}

export default PlannerForm;
