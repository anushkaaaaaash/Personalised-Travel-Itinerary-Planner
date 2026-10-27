// Planning-only limit; saved preference records are never truncated or rewritten.
export const MAX_PLANNING_DAYS = 14;
export function planningDateError(form, { adaptiveEnabled = false } = {}) {
  if (adaptiveEnabled === true) return '';
  const start = Date.parse(`${form?.startDate}T00:00:00Z`);
  const end = Date.parse(`${form?.endDate}T00:00:00Z`);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return '';
  const days = Math.round((end - start) / 86400000) + 1;
  return days > MAX_PLANNING_DAYS ? `Choose a trip of 1–14 days. These dates cover ${days} days; shorten the end date to continue.` : '';
}
