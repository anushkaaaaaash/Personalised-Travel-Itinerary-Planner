import { INTEREST_OPTIONS } from '../../../shared/tripPreferences.mjs';

const ACTIVITY_POOL = {
  culture: [
    { title: 'Museum morning', time: '09:30', duration: '2.5 hrs', note: 'Explore signature galleries and local exhibitions.' },
    { title: 'Heritage walking tour', time: '15:00', duration: '2 hrs', note: 'Guided stroll through neighborhoods and landmarks.' },
  ],
  food: [
    { title: 'Market breakfast', time: '08:30', duration: '1.5 hrs', note: 'Taste regional specialties at a neighborhood market.' },
    { title: 'Chef-recommended dinner', time: '19:30', duration: '2 hrs', note: 'Reservation at a well-reviewed local restaurant.' },
  ],
  adventure: [
    { title: 'Outdoor activity', time: '10:00', duration: '3 hrs', note: 'Kayak, hike, or cycle depending on local terrain.' },
    { title: 'Viewpoint challenge', time: '16:00', duration: '2 hrs', note: 'Reach a scenic overlook before sunset.' },
  ],
  nature: [
    { title: 'Park or garden visit', time: '09:00', duration: '2 hrs', note: 'Slow morning among greenery and waterfronts.' },
    { title: 'Golden-hour lookout', time: '17:30', duration: '1.5 hrs', note: 'Watch the light change over the landscape.' },
  ],
  nightlife: [
    { title: 'Sunset lounge', time: '18:30', duration: '2 hrs', note: 'Rooftop or waterfront drinks as the city lights up.' },
    { title: 'Live music night', time: '21:00', duration: '2 hrs', note: 'Catch a local band, jazz bar, or cultural show.' },
  ],
  shopping: [
    { title: 'Artisan boutiques', time: '11:00', duration: '2 hrs', note: 'Independent shops for crafts, textiles, and souvenirs.' },
    { title: 'Evening market', time: '18:00', duration: '1.5 hrs', note: 'Browse stalls and pick up last-minute finds.' },
  ],
  relaxation: [
    { title: 'Slow cafe morning', time: '09:00', duration: '1.5 hrs', note: 'Unhurried coffee and people-watching.' },
    { title: 'Spa or spa-like pause', time: '15:30', duration: '2 hrs', note: 'Reset with a massage, hammam, or quiet beach hour.' },
  ],
  history: [
    { title: 'Historic site visit', time: '10:00', duration: '2.5 hrs', note: 'Temples, forts, or old quarters with context.' },
    { title: 'Story of the city', time: '14:30', duration: '2 hrs', note: 'Museum or archive that explains how the place grew.' },
  ],
};

const FALLBACK_ACTIVITIES = [
  { title: 'Orientation walk', time: '09:00', duration: '2 hrs', note: 'Get your bearings and map favorite corners.' },
  { title: 'Signature landmark', time: '13:30', duration: '2 hrs', note: 'Visit the place travelers come here to see.' },
  { title: 'Neighborhood dinner', time: '19:00', duration: '2 hrs', note: 'Eat where locals go after work.' },
];

function toDate(value) {
  return new Date(`${value}T12:00:00Z`);
}

function formatDayLabel(date) {
  return date.toLocaleDateString(undefined, {
    timeZone: 'UTC',
    weekday: 'long',
    month: 'short',
    day: 'numeric',
  });
}

function dayCount(startDate, endDate) {
  const start = toDate(startDate);
  const end = toDate(endDate);
  const diff = Math.round((end - start) / (1000 * 60 * 60 * 24));
  return Math.max(1, diff + 1);
}

function pickActivities(interests, dayIndex) {
  const selected = interests.length ? interests : ['culture', 'food'];
  const slots = [];

  selected.forEach((interest, index) => {
    const pool = ACTIVITY_POOL[interest] || [];
    const activity = pool[(dayIndex + index) % pool.length];
    if (activity) {
      slots.push({
        ...activity,
        category: INTEREST_OPTIONS.find((item) => item.id === interest)?.label || interest,
      });
    }
  });

  while (slots.length < 3) {
    const fallback = FALLBACK_ACTIVITIES[slots.length % FALLBACK_ACTIVITIES.length];
    slots.push({ ...fallback, category: 'Explore' });
  }

  return slots.slice(0, 4);
}

function currencySymbol(code) {
  if (code === 'INR') return '₹';
  if (code === 'EUR') return '€';
  return '$';
}

export { INTEREST_OPTIONS };

export function buildPreviewItinerary(form) {
  const days = dayCount(form.startDate, form.endDate);
  const budget = Number(form.budget) || 0;
  const travelers = Number(form.travelers) || 1;
  const symbol = currencySymbol(form.currency);
  const lodging = Math.round(budget * 0.38);
  const food = Math.round(budget * 0.28);
  const activities = Math.round(budget * 0.22);
  const transport = Math.max(0, budget - lodging - food - activities);

  const previewDayCount = Math.min(days, 14);
  const itineraryDays = Array.from({ length: previewDayCount }, (_, index) => {
    const date = toDate(form.startDate);
    date.setUTCDate(date.getUTCDate() + index);

    return {
      day: index + 1,
      dateLabel: formatDayLabel(date),
      theme:
        index === 0
          ? `Arrival in ${form.destination}`
          : index === days - 1
            ? `Farewell to ${form.destination}`
            : `Discover ${form.destination}`,
      activities: pickActivities(form.interests, index),
    };
  });

  return {
    destination: form.destination,
    departureCity: form.departureCity,
    startDate: form.startDate,
    endDate: form.endDate,
    travelers,
    interests: form.interests,
    summary: `${days}-day trip from ${form.departureCity} to ${form.destination} for ${travelers} traveler${travelers > 1 ? 's' : ''}.`,
    estimatedBudget: {
      total: budget,
      perPerson: travelers ? Math.round(budget / travelers) : budget,
      currency: form.currency,
      symbol,
      breakdown: [
        { label: 'Stay', amount: lodging },
        { label: 'Food', amount: food },
        { label: 'Activities', amount: activities },
        { label: 'Local transport', amount: transport },
      ],
    },
    days: itineraryDays,
    totalDays: days,
    truncated: days > previewDayCount,
    source: 'sample',
  };
}
