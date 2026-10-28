import { useDestinationTheme } from '../themes/DestinationTheme.jsx';
import { sampleTrip } from '../data/sampleTrips.js';
import { useState } from 'react';
import SampleItinerary, { SampleChoices } from './SampleItinerary.jsx';
import { ArrowDown } from 'lucide-react';
import SiteHeader from './SiteHeader.jsx';
import JourneyArtwork from './JourneyArtwork.jsx';
export default function BrandWelcome({ loading = false, onUseSample }) {
  const [sampleId,setSampleId]=useState(null);
  useDestinationTheme(sampleTrip(sampleId)?.destination);
  return <div className="brand-welcome page">
    <SiteHeader />
    <section className="welcome-hero" aria-label="Welcome to Personalised Travel Planner">
      <div className="welcome-hero__copy"><p className="eyebrow">Less planning. More possibility.</p><h1>The world is full of stories.<br/><em>Go find yours.</em></h1><p>A thoughtful itinerary, shaped around your curiosity. Choose a place, find your rhythm, and leave a little room for wonder.</p><span className="welcome-hero__invite">{loading ? 'Getting your travel space ready' : 'Your next chapter starts below'} <ArrowDown size={16} aria-hidden="true" /></span></div>
      <div className="welcome-hero__art"><JourneyArtwork motif="mountains"/><span className="postcard-stamp">PLAN<br/><strong>YOUR WAY</strong><span aria-hidden="true">✦</span></span></div>
    </section>
    {!loading&&<section className="welcome-samples" aria-label="Try an itinerary example"><p className="eyebrow">Try a little inspiration</p><h2>Three places. An instant first look.</h2><p>Explore a prewritten three-day example, then make the details yours.</p><SampleChoices selected={sampleId} onSelect={setSampleId}/>{sampleId&&<SampleItinerary sampleId={sampleId} publicPreview onCustomize={()=>onUseSample?.(sampleId)}/>}</section>}
  </div>;
}
