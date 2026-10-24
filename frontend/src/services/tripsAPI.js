/** Named frontend facade: saving and generation remain distinct operations. */
import { createTrip } from './api.js';
import { getTrip, listTrips } from './tripHistory.js';
import { generateItinerary, refineItinerary } from './itineraries.js';
import { getRecommendations } from './recommendations.js';
import { optimizeItinerary } from './routeOptimization.js';
export const tripsAPI = { create: createTrip, list: listTrips, get: getTrip, generateItinerary, refineItinerary, optimizeItinerary, getRecommendations };
export default tripsAPI;
