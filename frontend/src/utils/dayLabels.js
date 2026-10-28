const DAY_MS = 86400000;
function calendarDay(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0,10) === value ? time : null;
}
export function tripDayLabel(date, tripStart) {
  const day=calendarDay(date),start=calendarDay(tripStart);
  if(day===null||start===null||day<start)return 'Day';
  return `Day ${String((day-start)/DAY_MS+1).padStart(2,'0')}`;
}
export function visibleDayRange(sections,tripStart) {
  const days=(sections || []).flatMap(section=>section.checkpoint?.itinerary?.days || []);
  if(!days.length)return 'No completed days on this page';
  return `${tripDayLabel(days[0].date,tripStart)}–${tripDayLabel(days.at(-1).date,tripStart)} · ${days[0].date} to ${days.at(-1).date}`;
}
