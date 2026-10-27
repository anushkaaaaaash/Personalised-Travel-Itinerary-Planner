import DestinationLoading from './DestinationLoading.jsx';
export default function RecommendationResults({ loading, error, result, onRetry, onCancel, destination }) {
  if (loading) return <DestinationLoading destination={destination} title="Finding your kind of adventure" status="Generating recommendations…" onCancel={onCancel} cancelLabel="Stop waiting for recommendations" />;
  if (error) return <section className="card"><h2>AI recommendations</h2><p role="alert">{error}</p><button className="preview-btn" onClick={onRetry}>Retry recommendations</button></section>;
  if (!result) return null;
  return <section className="card" aria-label="AI recommendations">
    <h2>AI recommendations for {result.destination}</h2>
    <p>AI-generated suggestions, not bookings or a complete itinerary. Costs are estimates for your whole group per option, not a trip total. Confirm prices, opening hours, dietary suitability and accessibility directly.</p>
    <p>Provider: {result.provider} · Model: {result.model}. Generating does not save or change your trip.</p>
    {result.warnings.length > 0 && <ul aria-label="Recommendation warnings">{result.warnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul>}
    {['attraction', 'activity', 'dining'].map((category) => {
      const items = result.recommendations.filter((item) => item.category === category);
      return items.length ? <section key={category} aria-label={category}><h3>{category === 'attraction' ? 'Attractions' : category === 'activity' ? 'Activities' : 'Dining'}</h3>
        {items.map((item) => <article key={item.id}><p className="eyebrow">AI-generated · unverified</p><h4>{item.name}</h4><p>{item.description}</p>
          <p><strong>Why recommended:</strong> {item.whyRecommended}</p>
          <p>Estimated group cost: {result.currency} {item.estimatedGroupCost}</p>
          <p>Interests: {item.interestTags.join(', ') || 'Not specified'} · Style: {item.travelStyle || 'Not specified'}</p>
          <p>Unverified AI dietary notes: {item.dietaryNotes || 'Not verified'}</p><p>Unverified AI mobility notes: {item.mobilityNotes || 'Not verified'}</p>
          <p className="hint">Dietary suitability and accessibility have not been verified. Confirm relevant ingredients, food preparation and access arrangements directly with the venue before relying on these suggestions.</p>
        </article>)}</section> : null;
    })}
  </section>;
}
