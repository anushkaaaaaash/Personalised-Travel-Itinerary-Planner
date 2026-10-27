import { useEffect, useState } from 'react';
import { useReducedMotion } from 'framer-motion';
import { Compass, MapPin, Plane, Pause, Play } from 'lucide-react';
import { createLoadingDeck } from '../data/destinationFacts.js';

export default function DestinationLoading(props) {
  return <LoadingSession key={props.destination || ''} {...props} />;
}

function LoadingSession({ destination = '', title = 'Your trip is taking shape', status = 'Putting your days together…', onCancel, cancelLabel = 'Stop waiting', embedded = false }) {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reducedMotion = useReducedMotion();
  const [cards] = useState(() => createLoadingDeck(destination));
  const exhausted = index === cards.length - 1;
  const next = () => setIndex(current => Math.min(current + 1, cards.length - 1));
  useEffect(() => {
    if (paused || reducedMotion || exhausted) return;
    const timer = setInterval(() => setIndex(current => Math.min(current + 1, cards.length - 1)), 9000);
    return () => clearInterval(timer);
  }, [paused, reducedMotion, exhausted, cards.length]);
  const card = cards[index];
  return <section className={`${embedded ? '' : 'card '}destination-loading${paused || reducedMotion || exhausted ? ' destination-loading--paused' : ''}`} aria-label="Trip planning in progress">
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
        <p className="hint">Good plans take a little care. This can take a few minutes.</p>
        <div className="destination-loading__pulse" aria-hidden="true"><span /><span /><span /></div>
      </div>
    </div>
    <div className="destination-loading__postcard" aria-live="off" key={card.title}>
      <p className="eyebrow">{card.label}</p>
      <h3>{card.title}</h3><p>{card.text}</p>
      {card.source && <a href={card.source} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">Source: {card.sourceLabel} ↗</a>}
      <div className="destination-loading__card-controls">
        <span>{exhausted ? 'Enjoy the anticipation' : 'Notes for the journey'}</span>
        <div>{!reducedMotion && !exhausted && <button type="button" onClick={() => setPaused(value => !value)} aria-label={paused ? 'Resume rotating cards and animation' : 'Pause rotating cards and animation'}>{paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}{paused ? 'Resume' : 'Pause'}</button>}
        <button type="button" onClick={next} disabled={exhausted}>{exhausted ? 'All notes explored' : 'Next note'}</button></div>
      </div>
    </div>
    {onCancel && <div className="destination-loading__footer"><button type="button" className="preview-btn" onClick={onCancel}>{cancelLabel}</button></div>}
  </section>;
}
