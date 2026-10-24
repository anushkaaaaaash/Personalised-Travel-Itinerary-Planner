/** A changed place name invalidates its old coordinates; never route to the old place. */
export function editActivity(day, index, key, value) {
  const updated = { ...day, activities: day.activities.map((activity, i) => i === index
    ? { ...activity, [key]: value, ...(key === 'title' && value !== activity.title ? { latitude: null, longitude: null } : {}) }
    : activity) };
  if (key === 'kind' && updated.activities.every(a => a.kind && a.kind !== 'unknown')) {
    updated.mainActivityCount = updated.activities.filter(a => a.kind === 'main').length;
  }
  return updated;
}
