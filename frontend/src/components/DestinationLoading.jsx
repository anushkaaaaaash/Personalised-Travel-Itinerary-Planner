import { useEffect, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { Compass, MapPin, Plane, Pause, Play } from 'lucide-react';
import { destinationCards } from '../data/destinationFacts.js';

export default function DestinationLoading({ destination = '', title = 'Your trip is taking shape', status = 'Waiting for your AI itinerary…', onCancel, cancelLabel = 'Stop waiting', embedded = false }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reducedMotion = useReducedMotion();
  const cards = destinationCards(destination);
  useEffect(() => { setIndex(0); }, [destination]);
  useEffect(() => {
    if (paused || reducedMotion) return;
    const timer = setInterval(() => setIndex(current => (current + 1) % cards.length), 9000);
    return () => clearInterval(timer);
  }, [destination, paused, reducedMotion, cards.length]);
  const card = cards[index % cards.length];
  return <section className={`${embedded ? '' : 'card '}destination-loading${paused ? ' destination-loading--paused' : ''}`} aria-label="AI trip planning in progress">
    <div className="destination-loading__intro">
      <div className="destination-loading__map" aria-hidden="true">
        <div className="destination-loading__orbit" />
        <MapPin className="destination-loading__pin" size={27} />
        <Plane className="destination-loading__plane" size={30} />
        <Compass className="destination-loading__compass" size={70} strokeWidth={1} />
        <span className="destination-loading__map-label">THE NEXT ADVENTURE</span>
      </div>
      <div className="destination-loading__copy">
        <p className="eyebrow">A little wanderlust while you wait</p>
        <h2>{title}</h2>
        {destination && <p className="destination-loading__destination"><MapPin size={16} aria-hidden="true" /> {destination}</p>}
        <p role="status" aria-live="polite">{status}</p>
        <p className="hint">This can take a few minutes. Keep this page open while we wait for a checked response.</p>
        <div className="destination-loading__pulse" aria-hidden="true"><span /><span /><span /></div>
      </div>
    </div>
    <div className="destination-loading__postcard" aria-live="off">
      <p className="eyebrow">{card.label}</p>
      <h3>{card.title}</h3><p>{card.text}</p>
      {card.source && <a href={card.source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Source: {card.sourceLabel} ↗</a>}
      <div className="destination-loading__card-controls">
        <span>{index % cards.length + 1} of {cards.length} cards · not a progress indicator</span>
        <div>{!reducedMotion && <button type="button" onClick={() => setPaused(value => !value)} aria-label={paused ? 'Resume rotating cards and animation' : 'Pause rotating cards and animation'}>{paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}{paused ? 'Resume' : 'Pause'}</button>}
        <button type="button" onClick={() => setIndex(current => (current + 1) % cards.length)}>Next {card.source ? 'fact' : 'tip'}</button></div>
      </div>
    </div>
    {onCancel && <div className="destination-loading__footer"><button type="button" className="preview-btn" onClick={onCancel}>{cancelLabel}</button><p className="hint">Stopping only ends your wait here; AI processing may continue. Nothing is saved automatically.</p></div>}
  </section>;
}
