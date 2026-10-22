function money(symbol, amount) {
  return `${symbol}${Number(amount).toLocaleString()}`;
}

function ItineraryResults({ itinerary, loading, error }) {
  if (loading) {
    return (
      <section className="card results" aria-live="polite" aria-busy="true">
        <div className="loading">
          <span className="spinner" aria-hidden="true" />
          <div>
            <h2>Charting your route</h2>
            <p>Checking the planner service and assembling a day-by-day preview…</p>
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
        <h2>Could not generate just yet</h2>
        <p>{error}</p>
      </section>
    );
  }

  if (!itinerary) {
    return (
      <section className="card results results--empty">
        <h2>Your itinerary will appear here</h2>
        <p>
          Fill in the form and press Generate Itinerary. We will map activities, pacing, and a
          budget split for each day.
        </p>
      </section>
    );
  }

  const { estimatedBudget } = itinerary;

  return (
    <section className="results-wrap">
      <article className="card results-hero">
        <p className="eyebrow">Trip preview</p>
        <h2>
          {itinerary.departureCity} → {itinerary.destination}
        </h2>
        <p>{itinerary.summary}</p>
        <p className="hint">
          This is a structured preview from your form. AI itinerary generation will use the
          backend once that API is available.
        </p>
      </article>

      <article className="card budget-card">
        <h3>Estimated budget</h3>
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
