import { ArrowUpRight, Compass } from 'lucide-react';
const destinations = [
  { name: 'Kyoto, Japan', city: 'Kyoto', caption: 'Quiet corners. Lasting impressions.', style: 'kyoto', symbol: '京' },
  { name: 'Goa, India', city: 'Goa', caption: 'A little more room to slow down.', style: 'goa', symbol: '☀' },
  { name: 'Paris, France', city: 'Paris', caption: 'Take the scenic way through.', style: 'paris', symbol: '✦' },
];
export default function DestinationDiscovery({ destination, onSelect }) {
  return <aside className="discovery" aria-label="Destination inspiration">
    <div className="discovery-heading"><Compass size={18} /><span>A place to begin</span></div>
    <h2>Where will your<br /><em>curiosity take you?</em></h2>
    <p>Pick a place that calls to you, or make a plan for somewhere entirely your own.</p>
    <div className="destination-tiles">{destinations.map(place => <button type="button" key={place.city} className={`destination-tile destination-tile--${place.style}`} aria-pressed={destination === place.name} onClick={() => onSelect(place.name)}>
      <span className="destination-art" aria-hidden="true"><span>{place.symbol}</span></span>
      <span className="destination-tile-copy"><strong>{place.city}</strong><small>{place.caption}</small></span><ArrowUpRight size={20} aria-hidden="true" />
    </button>)}</div>
    <p className="discovery-footnote">Your dates. Your pace. A trip with room to breathe.</p>
  </aside>;
}
