function money(symbol, amount) {
  return `${symbol}${Number(amount).toLocaleString()}`;
}

function ItineraryResults({ itinerary, loading, error, savedTrip, generated = false }) {
  if (loading) {
    return (
      <section className="card results" aria-live="polite" aria-busy="true">
        <div className="loading">
          <span className="spinner" aria-hidden="true" />
          <div>
            <h2>Saving your preferences</h2>
            <p>Waiting for the backend to confirm the saved trip ID…</p>
          </div>
        </div>
        <div className="skeleton-stack">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton skeleton--short" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="card results results--error" role="alert">
        <h2>Trip preferences need attention</h2>
        <p>{error}</p>
      </section>
    );
  }

  const confirmation = savedTrip ? (
    <article className="card save-confirmation" role="status">
      <h2>Trip preferences saved</h2>
      <p>Confirmed trip ID: <strong>{savedTrip.id}</strong></p>
      <p className="hint">Your preferences were saved by the backend. {generated ? 'AI generation is separate and is not stored with this record.' : 'An itinerary has not been generated.'}</p>
    </article>
  ) : null;

  if (!itinerary) {
    return (
      <section className="results-wrap">
        {confirmation}
        <article className="card results results--empty">
          <h2>Your trip preferences</h2>
          <p>Complete the form and choose Save trip preferences. A saved confirmation appears only after the backend returns a trip ID.</p>
          <p className="hint">Show sample preview works without saving. Its activities and budget split are illustrative, not real recommendations or bookings.</p>
        </article>
      </section>
    );
  }

  const { estimatedBudget } = itinerary;

  return (
    <section className="results-wrap">
      {confirmation}
      <article className="card results-hero">
        <p className="eyebrow">Sample preview · not generated or booked</p>
        <h2>
          {itinerary.departureCity} → {itinerary.destination}
        </h2>
        <p>{itinerary.summary}</p>
        <p className="hint">
          This sample uses fixed activities and budget percentages, not live recommendations.
          Showing it does not save your trip or apply dietary needs and travel pace. Use Generate AI day-by-day itinerary for a separate AI request.
        </p>
        {itinerary.truncated && <p className="hint">Showing the first 14 of {itinerary.totalDays} days only.</p>}
      </article>

      <article className="card budget-card">
        <h3>Illustrative budget split</h3>
        <div className="budget-total">
          <strong>{money(estimatedBudget.symbol, estimatedBudget.total)}</strong>
          <span>
            {money(estimatedBudget.symbol, estimatedBudget.perPerson)} per traveler
          </span>
        </div>
        <ul className="budget-list">
          {estimatedBudget.breakdown.map((item) => (
            <li key={item.label}>
              <span>{item.label}</span>
              <span>{money(estimatedBudget.symbol, item.amount)}</span>
            </li>
          ))}
        </ul>
      </article>

      <div className="day-grid">
        {itinerary.days.map((day) => (
          <article className="card day-card" key={day.day}>
            <header>
              <span className="day-badge">Day {day.day}</span>
              <div>
                <h3>{day.theme}</h3>
                <p>{day.dateLabel}</p>
              </div>
            </header>
            <ul className="activity-list">
              {day.activities.map((activity) => (
                <li key={`${day.day}-${activity.title}`}>
                  <div className="activity-meta">
                    <time>{activity.time}</time>
                    <span>{activity.duration}</span>
                    <span className="tag">{activity.category}</span>
                  </div>
                  <strong>{activity.title}</strong>
                  <p>{activity.note}</p>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  );
}

export default ItineraryResults;
