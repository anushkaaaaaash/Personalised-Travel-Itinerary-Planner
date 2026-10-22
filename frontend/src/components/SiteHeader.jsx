function SiteHeader() {
  return (
    <header className="site-header">
      <div className="site-header__brand">
        <span className="site-header__mark" aria-hidden="true">
          ✈
        </span>
        <div>
          <p className="site-header__eyebrow">Wander, well planned</p>
          <h1>Personalized Travel Itinerary Planner</h1>
        </div>
      </div>
      <p className="site-header__lede">
        Tell us where you want to go. We will shape a day-by-day trip around your dates,
        budget, and interests.
      </p>
    </header>
  );
}

export default SiteHeader;
