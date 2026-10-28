import SiteHeader from './SiteHeader.jsx';
import { Link, Route, Routes } from 'react-router-dom';
import PlannerPage from '../pages/PlannerPage.jsx';
import SavedTripPage from '../pages/SavedTripPage.jsx';
import SavedAdaptiveTripPage from '../pages/SavedAdaptiveTripPage.jsx';
import SavedTripsPage from '../pages/SavedTripsPage.jsx';
export default function PlannerRoutes({signedIn,ownershipEnabled,savedOnly=false,jobsEnabled=false,adaptiveEnabled=false,adaptivePolicy=null,adaptiveSavedTripsEnabled=false}) {
  return <Routes><Route path="/" element={<PlannerPage legacyEnabled={!savedOnly} signedIn={signedIn} ownershipEnabled={ownershipEnabled} jobsEnabled={jobsEnabled === true} adaptiveEnabled={adaptiveEnabled === true} adaptivePolicy={adaptivePolicy} adaptiveSavedTripsEnabled={adaptiveSavedTripsEnabled === true}/>}/>
    <Route path="/saved-trips" element={signedIn?<SavedTripsPage adaptiveSavedTripsEnabled={adaptiveSavedTripsEnabled === true}/>:<div className="page"><SiteHeader/><main className="card route-message"><h1>Sign in to browse your saved trips</h1><p>Use the account form above to continue.</p><Link to="/">Back to planner</Link></main></div>}/>
    <Route path="/saved-adaptive-trips/:tripID" element={signedIn?<SavedAdaptiveTripPage/>:<div className="page"><SiteHeader/><main className="card route-message"><h1>Sign in to open your saved trip</h1><p>Your saved trip stays selected after sign-in.</p><Link to="/">Back to planner</Link></main></div>}/>
    <Route path="/itineraries/:tripID" element={signedIn?<SavedTripPage/>:<div className="page"><SiteHeader/><main className="card route-message"><h1>Sign in to open your saved itinerary</h1><p>Your trip stays selected after sign-in. Use the account form above to continue.</p><Link to="/">Back to planner</Link></main></div>}/>
    <Route path="*" element={<div className="page"><SiteHeader/><main className="card route-message"><h1>Page not found</h1><Link to="/">Back to planner</Link></main></div>}/></Routes>;
}
