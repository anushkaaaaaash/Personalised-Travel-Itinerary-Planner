import { Link, Route, Routes } from 'react-router-dom';
import PlannerPage from '../pages/PlannerPage.jsx';
import SavedTripPage from '../pages/SavedTripPage.jsx';
export default function PlannerRoutes({signedIn,ownershipEnabled,savedOnly=false,jobsEnabled=false}) {
  return <Routes><Route path="/" element={<PlannerPage legacyEnabled={!savedOnly} signedIn={signedIn} ownershipEnabled={ownershipEnabled} jobsEnabled={jobsEnabled === true}/>}/>
    <Route path="/itineraries/:tripID" element={signedIn?<SavedTripPage/>:<main className="page card"><h1>Sign in to open your saved itinerary</h1><p>Your trip stays selected after sign-in. Use the account form above to continue.</p><Link to="/">Back to planner</Link></main>}/>
    <Route path="*" element={<main className="page card"><h1>Page not found</h1><Link to="/">Back to planner</Link></main>}/></Routes>;
}
