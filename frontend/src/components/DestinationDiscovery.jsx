import { ArrowUpRight, Sparkles } from 'lucide-react';
import { useTheme } from '../themes/DestinationTheme.jsx';
import JourneyArtwork from './JourneyArtwork.jsx';
import { SAMPLE_TRIPS as destinations } from '../data/sampleTrips.js';
export default function DestinationDiscovery({ destination, onSelect, disabled=false }) {
  const { theme, countries } = useTheme();
  return <aside className="discovery" aria-label="Destination inspiration">
    <div className="discovery-heading"><Sparkles size={17} aria-hidden="true"/><span>A place to begin</span></div>
    <h1>Follow your<br/><em>somewhere.</em></h1>
    <p>A city you’ve dreamed of. A coast you’ve never seen. A few days that feel entirely like you.</p>
    <div className="discovery-postcard" key={theme.code}><JourneyArtwork motif={theme.motif}/><div className="discovery-postcard__caption"><span><small>{theme.code === 'WORLD' ? 'YOUR NEXT CHAPTER' : `THE COLOURS OF ${theme.name.toUpperCase()}`}</small><strong>{theme.story}</strong></span><span className="postcard-coordinate" aria-hidden="true">{theme.code === 'WORLD' ? 'R / 01' : theme.code}</span></div></div>
    <div className="destination-tiles">{destinations.map(place => <button type="button" key={place.city} className={`destination-tile destination-tile--${place.id}`} aria-pressed={destination === place.destination} disabled={disabled} onClick={() => onSelect(place.id)}>
      <span className="destination-art" aria-hidden="true"><span>{place.symbol}</span></span>
      <span className="destination-tile-copy"><small>{place.country}</small><strong>{place.city}</strong><span>{place.caption}</span></span><ArrowUpRight size={18} aria-hidden="true"/>
    </button>)}</div>
    <p className="discovery-footnote">{countries.length ? `${countries.length} destination palettes. ` : ''}Choose a city for an instant sample and editable trip settings.</p>
  </aside>;
}
