import { SAMPLE_TRIPS, sampleTrip } from '../data/sampleTrips.js';

export function SampleChoices({selected,onSelect,disabled=false}) {
  return <div className="destination-tiles" aria-label="Instant itinerary examples">{SAMPLE_TRIPS.map(place=><button type="button" key={place.id} disabled={disabled} className={`destination-tile destination-tile--${place.id}`} aria-pressed={selected===place.id} onClick={()=>onSelect(place.id)}><span className="destination-art" aria-hidden="true"><span>{place.symbol}</span></span><span className="destination-tile-copy"><small>{place.country}</small><strong>{place.city}</strong><span>{place.caption}</span></span></button>)}</div>;
}

export default function SampleItinerary({sampleId,onCustomize,onPreferences,onReview,publicPreview=false}) {
  const sample=sampleTrip(sampleId);if(!sample)return null;
  return <section className="card sample-itinerary" aria-label={`${sample.city} prewritten sample itinerary`}>
    <p className="eyebrow">Instant example · 3 days</p><h2>A little {sample.city} inspiration</h2>
    <p>This is a prewritten sample, not a newly generated or booked trip. It starts in {sample.city}; travel from your home is not included.</p>
    <p className="hint">The day numbers are illustrative—not your travel dates. Choose your dates and starting city before building your own plan.</p>
    {sample.days.map((day,index)=><details className="adaptive-day" key={day.title} open={index===0}><summary>Day {String(index+1).padStart(2,'0')} · {day.title}</summary><div className="day-notes"><p><strong>Morning</strong><br/>{day.morning}</p><p><strong>Afternoon</strong><br/>{day.afternoon}</p><p><strong>Evening</strong><br/>{day.evening}</p></div></details>)}
    <p className="hint">Example settings: 2 travellers · {sample.currency} {sample.budget.toLocaleString()} total budget. This is an editable allowance, not a price estimate. Check opening days, transport and tickets for your dates.</p>
    <a href={sample.source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Destination ideas: {sample.sourceLabel} ↗</a>
    <div className="step-actions"><button type="button" className="generate-btn" onClick={onCustomize}>{publicPreview?'Use this example':'Edit dates & starting point'}</button>{onPreferences&&<button type="button" className="preview-btn" onClick={onPreferences}>Adjust preferences</button>}{onReview&&<button type="button" className="preview-btn" onClick={onReview}>Review my settings</button>}</div>
  </section>;
}
