/** Keep transport diagnostics out of the travel experience without exposing server text. */
export function travelError(message, fallback='We couldn’t finish that request. Please try again.') {
  const value=String(message || '');
  if(/1[–-]14 days/.test(value))return 'Choose a trip of 1–14 days, then try again.';
  if(/activity limit.*pace|pace.*activity limit/i.test(value))return 'Choose a daily activity limit that fits your travel pace.';
  if(/fixed activities|fixed commitments/i.test(value))return 'Allow room for your fixed activities, or change their times.';
  if(/rate limit|too many/i.test(value))return 'The planner is busy. Give it a moment, then try again.';
  if(/timed out|timeout/i.test(value))return 'This trip is taking longer than expected. Please try again.';
  if(/sign in|session.*expired/i.test(value))return 'Please sign in again to continue.';
  return fallback;
}
