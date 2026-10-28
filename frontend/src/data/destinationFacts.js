// Small, local editorial collection. Sources checked 2026-10-27; no runtime fetch.
// Destinations are free text: only exact aliases match, never ambiguous substrings.
const kyotoSource = 'https://whc.unesco.org/en/list/688/';
const goaSource = 'https://whc.unesco.org/en/list/234/';
const facts = {
  kyoto: [
    { title: 'A thousand years of stories', text: 'Founded in 794, Kyoto served as Japan’s imperial capital until the mid-19th century.', source: kyotoSource },
    { title: 'Heritage beyond one city', text: 'The Ancient Kyoto World Heritage site brings together 17 places across Kyoto, Uji and Otsu.', source: kyotoSource },
    { title: 'Gardens with a global influence', text: 'UNESCO recognizes Kyoto’s historic gardens for their influence on garden design around the world.', source: kyotoSource },
  ],
  goa: [
    { title: 'More than a coastline', text: 'The Churches and Convents of Goa joined UNESCO’s World Heritage List in 1986.', source: goaSource },
    { title: 'A meeting of architectural traditions', text: 'Goa’s historic churches helped spread European architectural and artistic styles across Asia.', source: goaSource },
    { title: 'A landmark in Old Goa', text: 'The Basilica of Bom Jesus contains the tomb of St Francis Xavier.', source: goaSource },
  ],
};
const extraFacts = {
  paris: { title: 'A city told by its river', text: 'Paris’s UNESCO-listed Seine riverbanks connect landmarks including the Louvre, Notre-Dame and the Eiffel Tower.', source: 'https://whc.unesco.org/en/list/600/', sourceLabel: 'UNESCO' },
  tokyo: { title: 'From Edo to Tokyo', text: 'The city once called Edo was renamed Tokyo in 1868.', source: 'https://www.gotokyo.org/en/see-and-do/history/index.html', sourceLabel: 'GO TOKYO' },
  rome: { title: 'Layers of history', text: 'Rome’s World Heritage historic centre includes the Colosseum, the Pantheon and the Roman Forums.', source: 'https://whc.unesco.org/en/list/91/', sourceLabel: 'UNESCO' },
  london: { title: 'Follow the Thames', text: 'The Thames runs through central London, past landmarks such as Tower Bridge and the London Eye.', source: 'https://www.visitlondon.com/things-to-do/london-areas/river-thames/thames-river-and-waterways', sourceLabel: 'Visit London' },
};
const aliases = new Map([
  ['kyoto', 'kyoto'], ['kyoto, japan', 'kyoto'], ['goa', 'goa'], ['goa, india', 'goa'],
  ['paris', 'paris'], ['paris, france', 'paris'], ['tokyo', 'tokyo'], ['tokyo, japan', 'tokyo'],
  ['rome', 'rome'], ['rome, italy', 'rome'], ['roma', 'rome'], ['london', 'london'], ['london, uk', 'london'], ['london, england', 'london'], ['london, united kingdom', 'london'],
]);
const localTips = {
  kyoto:[
    {title:'Keep a Kyoto day on one side of the city',text:'Try a Higashiyama day and a separate Arashiyama day, rather than repeatedly crossing Kyoto between stops.'},
    {title:'Give the temple lanes breathing room',text:'Leave a tea break between Higashiyama visits. Hilly lanes and tempting side streets deserve time.'},
    {title:'Plan a flexible Fushimi walk',text:'Decide how much climbing suits your group before making a long shrine walk the day’s main event.'},
  ],
  goa:[
    {title:'Choose your Goa base first',text:'A Panaji heritage day and a distant south-Goa beach day need different transfer plans. Avoid treating the whole state as one compact resort.'},
    {title:'Pair Old Goa with Panaji',text:'Consider a heritage outing from a Panaji base, with a relaxed lunch and time to return, rather than adding another long coastal transfer.'},
    {title:'Keep a coastal alternative',text:'For a Goa beach day, keep a town or café option available if local conditions make the coast less appealing.'},
  ],
  paris:[
    {title:'One Paris museum can be enough',text:'Choose a focused museum visit and a nearby walk instead of scheduling several large collections on the same day.'},
    {title:'Leave room for Montmartre’s slopes',text:'Build rest stops into a Montmartre outing and check step-free options if your group needs them.'},
    {title:'Let the river shape the afternoon',text:'Consider a Seine-side walk after a central Paris visit, leaving a café pause rather than filling every gap.'},
  ],
};
const tips = [
  { title: 'Leave room for a detour', text: 'Keep a little unscheduled time for a neighborhood walk, a longer lunch or an unexpected discovery.' },
  { title: 'Check before you set off', text: 'Confirm opening hours, reservations and accessibility directly with venues before you travel.' },
  { title: 'Make the journey part of the day', text: 'Allow time between activities for transport, rest and finding your way.' },
  { title: 'A small offline safety net', text: 'Download a map of your destination and keep your accommodation address available offline.' },
  { title: 'Start with one great anchor', text: 'Choose one experience you really want each day, then let smaller discoveries fill the gaps.' },
  { title: 'Your first day can be lighter', text: 'Allow a little breathing room after arrival for getting settled, a meal and a short walk.' },
  { title: 'Keep the essentials close', text: 'Pack medication, charging cables and a change of clothes in your carry-on where permitted.' },
  { title: 'Reservations deserve a reminder', text: 'Check cancellation deadlines and set a reminder for any timed tickets or restaurant bookings.' },
  { title: 'Plan for a change of weather', text: 'Keep an indoor alternative in mind for an outdoor day, and check the forecast close to departure.' },
  { title: 'Make room for your own rhythm', text: 'A slower morning or an afternoon break can be part of a great itinerary, not time lost.' },
  { title: 'Keep a useful address card', text: 'Save your accommodation name and address in the local writing system when available.' },
  { title: 'A few words go a long way', text: 'Learn a greeting, “please” and “thank you” in the language used at your destination.' },
  { title: 'Check the whole journey', text: 'Before reserving an early activity, check how you will get there and how much time the trip needs.' },
  { title: 'Leave a cushion in the budget', text: 'Set aside some spending money for small extras, transport changes and spontaneous discoveries.' },
  { title: 'Travel light on a day out', text: 'Bring water, a charged phone and the essentials you need, rather than carrying everything all day.' },
  { title: 'Make a little meeting plan', text: 'If your group splits up, agree on a meeting place and time in case someone loses their connection.' },
  { title: 'Check what a ticket includes', text: 'Look for entry times, included areas, identification requirements and re-entry rules before booking.' },
  { title: 'Save space for a favorite', text: 'You do not have to see everything. Returning to a place you love can be just as rewarding.' },
  { title: 'Think beyond the entrance', text: 'For access needs, check the route to the venue as well as entrances, lifts and rest facilities.' },
  { title: 'A pocket-size backup', text: 'Keep essential booking references somewhere you can reach even without a mobile connection.' },
  { title: 'Ask before you photograph', text: 'Check posted photography rules and ask permission before taking close-up photographs of people.' },
  { title: 'Give departure day some space', text: 'Leave a generous buffer for packing, check-out and the journey to your departure point.' },
  { title: 'A meal can be the main event', text: 'Keep time for a relaxed meal instead of treating every stop as something to rush through.' },
  { title: 'Know your must-haves', text: 'Make a short list of what matters most to your group so changes are easier to agree on.' },

];
export function destinationCards(destination = '') {
  const normalized = String(destination).trim().toLowerCase().replace(/\s+/g, ' ').replace(/\s*,\s*/g, ', ');
  const key = aliases.get(normalized);
  const generalTips = tips.map(tip => ({ ...tip, label: 'General travel tip' }));
  const placeTips=(localTips[key] || []).map(tip=>({...tip,label:'Destination planning tip'}));
  if (!key) return generalTips;
  if (Object.hasOwn(extraFacts, key)) return [{ ...extraFacts[key], label: 'Destination fact' }, ...placeTips, ...generalTips];
  return [...facts[key].map(fact => ({ ...fact, label: 'Destination fact', sourceLabel: 'UNESCO' })), ...placeTips, ...generalTips];
}

// Each mounted planning run consumes this finite deck once. Never wrap to the start.
export function createLoadingDeck(destination = '', random = Math.random) {
  const cards = destinationCards(destination).map(card => ({ ...card }));
  for (let i = cards.length - 1; i > 0; i -= 1) {
    const j = Math.floor(random() * (i + 1));
    [cards[i], cards[j]] = [cards[j], cards[i]];
  }
  // Ground the first impression in the chosen destination whenever a source exists.
  const firstFact = cards.findIndex(card => card.source);
  if (firstFact > 0) [cards[0], cards[firstFact]] = [cards[firstFact], cards[0]];
  return [...cards, {
    label: 'While you wait',
    title: 'A little space for anticipation',
    text: 'Your trip is still taking shape. Think of the one experience you most want to bring home a memory of.',
  }];
}
