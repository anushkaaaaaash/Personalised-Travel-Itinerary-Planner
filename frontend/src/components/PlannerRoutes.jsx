import SiteHeader from './SiteHeader.jsx';
import { Link, Route, Routes } from 'react-router-dom';
import PlannerPage from '../pages/PlannerPage.jsx';
import SavedTripPage from '../pages/SavedTripPage.jsx';
export default function PlannerRoutes({signedIn,ownershipEnabled,savedOnly=false,jobsEnabled=false,adaptiveEnabled=false,adaptivePolicy=null}) {
  return <Routes><Route path="/" element={<PlannerPage legacyEnabled={!savedOnly} signedIn={signedIn} ownershipEnabled={ownershipEnabled} jobsEnabled={jobsEnabled === true} adaptiveEnabled={adaptiveEnabled === true} adaptivePolicy={adaptivePolicy}/>}/>
    <Route path="/itineraries/:tripID" element={signedIn?<SavedTripPage/>:<div className="page"><SiteHeader/><main className="card route-message"><h1>Sign in to open your saved itinerary</h1><p>Your trip stays selected after sign-in. Use the account form above to continue.</p><Link to="/">Back to planner</Link></main></div>}/>
    <Route path="*" element={<div className="page"><SiteHeader/><main className="card route-message"><h1>Page not found</h1><Link to="/">Back to planner</Link></main></div>}/></Routes>;
}
