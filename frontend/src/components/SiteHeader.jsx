import { Plane } from 'lucide-react';
function SiteHeader() {
  return (
    <header className="site-header">
      <div className="site-header__brand">
        <span className="site-header__mark" aria-hidden="true">
          <Plane size={25} aria-hidden="true" />
        </span>
        <div>
          <p className="site-header__eyebrow">Wander, well planned</p>
          <h1>Personalized Travel Itinerary Planner</h1>
        </div>
      </div>
      <p className="site-header__lede">
        Tell us where you want to go. Capture your dates, budget, and interests,
        then review AI suggestions and a day-by-day plan. Save preferences separately.
      </p>
    </header>
  );
}

export default SiteHeader;
