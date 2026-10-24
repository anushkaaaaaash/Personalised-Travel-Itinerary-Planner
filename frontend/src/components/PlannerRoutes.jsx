import { Link, Route, Routes } from 'react-router-dom';
import PlannerPage from '../pages/PlannerPage.jsx';
import SavedTripPage from '../pages/SavedTripPage.jsx';
export default function PlannerRoutes({signedIn,ownershipEnabled}) {
  return <Routes><Route path="/" element={<PlannerPage signedIn={signedIn} ownershipEnabled={ownershipEnabled}/>}/>
    <Route path="/itineraries/:tripID" element={signedIn?<SavedTripPage/>:<main className="page card"><h1>Sign in to open your saved itinerary</h1><p>Use the account form above. This private URL stays selected after sign-in. Refresh ends the in-memory session.</p><Link to="/">Back to planner</Link></main>}/>
    <Route path="*" element={<main className="page card"><h1>Page not found</h1><Link to="/">Back to planner</Link></main>}/></Routes>;
}
