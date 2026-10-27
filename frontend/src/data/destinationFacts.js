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
const tips = [
  { title: 'Leave room for a detour', text: 'Keep a little unscheduled time for a neighborhood walk, a longer lunch or an unexpected discovery.' },
  { title: 'Check before you set off', text: 'Confirm opening hours, reservations and accessibility directly with venues before you travel.' },
  { title: 'Make the journey part of the day', text: 'Allow time between activities for transport, rest and finding your way.' },
];
export function destinationCards(destination = '') {
  const normalized = String(destination).trim().toLowerCase().replace(/\s+/g, ' ').replace(/\s*,\s*/g, ', ');
  const key = aliases.get(normalized);
  const generalTips = tips.map(tip => ({ ...tip, label: 'General travel tip' }));
  if (!key) return generalTips;
  if (Object.hasOwn(extraFacts, key)) return [{ ...extraFacts[key], label: 'Destination fact' }, ...generalTips];
  return facts[key].map(fact => ({ ...fact, label: 'Destination fact', sourceLabel: 'UNESCO' }));
}
