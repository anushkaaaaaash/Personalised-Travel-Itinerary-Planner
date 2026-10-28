import { createInitialForm } from '../utils/tripPreferences.js';

export const SAMPLE_TRIPS = Object.freeze([
  {id:'kyoto',destination:'Kyoto, Japan',city:'Kyoto',country:'Japan',symbol:'✿',caption:'Temples, tea and quiet lanes.',currency:'USD',budget:900,interests:['culture','food','nature'],travelPace:'balanced',source:'https://kyoto.travel/en/itineraries/',sourceLabel:'Kyoto City official guide',days:[
    {title:'Higashiyama & Gion',morning:'Start with Kiyomizu-dera and the lanes of Higashiyama, leaving time for the uphill walk.',afternoon:'Choose a nearby lunch and a tea break, then stroll toward Yasaka Shrine.',evening:'Explore public streets in Gion at an unhurried pace. Respect private lanes and photography signs.'},
    {title:'An Arashiyama day',morning:'Head to Arashiyama for the bamboo paths and a garden visit.',afternoon:'Stay in the same area for lunch and a riverside walk rather than crossing the city again.',evening:'Return to your accommodation area for dinner and a restful evening.'},
    {title:'Fushimi & a gentle finish',morning:'Visit Fushimi Inari; choose a shorter shrine walk or a longer climb to suit your energy.',afternoon:'Leave time for lunch, collecting bags and your onward journey.',evening:'Keep this flexible for departure rather than promising another timed attraction.'},
  ]},
  {id:'goa',destination:'Goa, India',city:'Goa',country:'India',symbol:'☀',caption:'Heritage lanes and a slower coast.',currency:'INR',budget:30000,interests:['relaxation','culture','food'],travelPace:'relaxed',source:'https://www.incredibleindia.gov.in/en/destinations/goa',sourceLabel:'Incredible India',days:[
    {title:'Panaji at your own pace',morning:'Settle into a Panaji base and explore the Fontainhas neighbourhood on foot.',afternoon:'Pause for a Goan lunch, then keep the afternoon light with a café or riverside walk.',evening:'Enjoy a relaxed dinner near your base; check the journey back before staying out late.'},
    {title:'Old Goa & an easy evening',morning:'Travel to Old Goa for its historic churches, allowing time for respectful visits.',afternoon:'Return toward Panaji for lunch and a break instead of adding a distant beach transfer.',evening:'Choose a nearby coastal outing if conditions suit, or stay in town for dinner.'},
    {title:'A little coast, then home',morning:'Plan a gentle beach walk near your base. Follow local weather and lifeguard advice.',afternoon:'Leave room for lunch, check-out and transfer to your departure point.',evening:'Keep the evening free for onward travel; north and south Goa are not interchangeable short hops.'},
  ]},
  {id:'paris',destination:'Paris, France',city:'Paris',country:'France',symbol:'✦',caption:'Art, river walks and café pauses.',currency:'EUR',budget:1000,interests:['culture','food','history'],travelPace:'balanced',source:'https://parisjetaime.com/decouvrir-paris/paris-en-1-2-ou-3-jours-i126',sourceLabel:'Paris tourist office',days:[
    {title:'The Louvre & the Seine',morning:'Choose a focused Louvre visit if tickets and opening days suit; avoid trying to see everything.',afternoon:'Have lunch nearby and take a slower walk through the Tuileries and along the Seine.',evening:'Keep dinner close to your accommodation or the river so the day ends without another long transfer.'},
    {title:'Montmartre without the rush',morning:'Explore Montmartre, allowing for slopes and steps around the hill.',afternoon:'Take a café lunch and choose one nearby stop rather than a cross-city checklist.',evening:'Enjoy dinner in the area or return early for a quieter night.'},
    {title:'A final Paris morning',morning:'Choose a neighbourhood walk or an Eiffel Tower-area outing that fits your departure time.',afternoon:'Reserve time for lunch, luggage and the station or airport transfer.',evening:'Leave this open for travel. Timed tickets and transport arrangements need checking for your actual dates.'},
  ]},
]);

export function sampleTrip(id) { return SAMPLE_TRIPS.find(item=>item.id===id || item.destination===id) || null; }
export function samplePreferences(id) {
  const sample=sampleTrip(id);
  return sample ? {...createInitialForm(),destination:sample.destination,departureCity:sample.city,currency:sample.currency,budget:sample.budget,interests:[...sample.interests],travelPace:sample.travelPace,travelStyle:'comfort'} : createInitialForm();
}
