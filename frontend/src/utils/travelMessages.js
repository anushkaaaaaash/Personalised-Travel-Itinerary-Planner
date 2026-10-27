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

const preferenceAdvice = {
  destination: [0, 'Enter the city or country you want to visit, using no more than 200 characters.'],
  departureCity: [0, 'Enter your departure city, using no more than 200 characters.'],
  startDate: [0, 'Choose a valid calendar date for the start of your trip.'],
  endDate: [0, 'Choose a valid end date on or after your start date.'],
  travelers: [1, 'Enter a whole number of travelers from 1 to 20.'],
  budget: [1, 'Enter a total budget greater than zero for the whole group and entire trip.'],
  currency: [1, 'Choose USD, EUR or INR for your total budget.'],
  interests: [1, 'Choose each travel interest only once from the listed options.'],
  dietaryNeeds: [1, 'Choose a listed dietary preference, or No specific preference.'],
  travelPace: [1, 'Choose a listed travel pace: relaxed, balanced or fast-paced.'],
  travelStyle: [1, 'Choose a listed travel style, or No specific preference.'],
  mobilityConcerns: [1, 'Keep your practical mobility preferences within 500 characters.'],
};

const invalidResultReasons = {
  FORMAT_SCHEMA: 'The returned plan was not in a usable format.',
  PREFERENCE_MISMATCH: 'The returned plan did not match your trip preferences.',
  DATE_COVERAGE: 'The returned plan did not cover your requested dates correctly.',
  PACE: 'The returned plan did not match your selected pace.',
  BUDGET: 'The returned plan did not pass the checks against your total budget.',
  TIMELINE: 'The returned plan contained an invalid or overlapping activity schedule.',
  VIBE_MISMATCH: 'The returned plan did not preserve your selected trip vibe.',
  FIXED_COMMITMENT: 'The returned plan changed a fixed activity that should have been kept.',
};

export function tripFailureRecovery({ code, reason, fields } = {}) {
  const recovery = (title, message, options = {}) => ({ code, title, message, retryable: true, editStep: null, recommendations: [], ...options });
  if (code === 'TRANSPORT_TIMEOUT') return recovery('Planning took too long.', 'The planning service reached its time limit before this request finished. Your trip details have not been identified as a problem. You can try again with the same details.');
  if (code === 'TRANSPORT_UNAVAILABLE') return recovery('We couldn’t reach the planner.', 'The connection to the planning service was interrupted. Check your connection, then try again with the same trip details.');
  if (code === 'SERVICE_UNAVAILABLE') return recovery('Planning is temporarily unavailable.', 'The planning service is not available right now. No changes to your trip details are needed; please try again later.');
  if (code === 'AI_RATE_LIMITED') return recovery('The planner is busy.', 'The planning service has temporarily limited requests. Wait a little before trying again. Your dates and preferences do not need to change.');
  if (code === 'AI_PROVIDER_FAILED') return recovery('The planning service couldn’t finish.', 'The service failed while producing your plan. This does not mean your trip details are invalid. You can try again with the same details.');
  if (code === 'AI_OUTPUT_TRUNCATED') return recovery('The returned plan was incomplete.', 'The service stopped before returning the complete plan, so we did not accept it. Your trip details are unchanged; this error does not require a shorter trip.');
  if (['AI_INVALID_RESPONSE', 'AI_SCHEMA_REJECTED', 'UNREADABLE_RESPONSE'].includes(code)) {
    const explanation = code === 'AI_INVALID_RESPONSE' && Object.hasOwn(invalidResultReasons, reason) ? invalidResultReasons[reason] : 'The service returned a plan we could not verify.';
    return recovery('The returned plan didn’t pass its checks.', `${explanation} We did not accept it. Your trip details are unchanged; try again with the same details.`);
  }
  if (code === 'AUTH_REQUIRED') return recovery('Please sign in again.', 'Your account session could not be verified. Sign in again before building your trip; changing your trip details will not fix this.', { retryable: false });
  if (code === 'REQUEST_TOO_LARGE') return recovery('This request is too large to process at once.', 'The service could not process the size of this request in one go. Your dates are unchanged; it needs a smaller planning section, not an automatically shortened trip.', { retryable: false });
  if (code === 'ITINERARY_DURATION_UNSUPPORTED') return recovery('This trip needs a different planning route.', 'This planning route cannot handle the whole date range in one request. Your dates are unchanged; support for planning the trip in sections is needed.', { retryable: false });
  if (code === 'REFINEMENT_FIXED_CONFLICT') return recovery('Your fixed activities need more room.', 'The requested daily activity limit cannot include all of your fixed activities. Increase that limit or review the fixed activities before trying again.', { retryable: false });
  if (code === 'REFINEMENT_PACE_CONFLICT') return recovery('The activity limit and pace don’t match.', 'The requested daily activity limit conflicts with your selected pace. Choose a compatible pace, or adjust the daily activity limit in your itinerary.', { retryable: false, editStep: 1, recommendations: [{field:'travelPace',suggestion:'Choose a pace that fits your daily activity limit, or keep this pace and adjust that limit in your itinerary.'}] });
  if (code === 'VALIDATION_ERROR') {
    const recommendations = [...new Set(Array.isArray(fields) ? fields : [])].filter(field => typeof field === 'string' && Object.hasOwn(preferenceAdvice, field)).map(field => ({field,suggestion:preferenceAdvice[field][1]}));
    return recovery('Let’s check your trip details.', recommendations.length ? 'The service identified these details to review. Your entries are kept; nothing will change until you edit them.' : 'The service rejected the trip details without identifying a specific field. Your entries are kept; review them before trying again.', {retryable:false,editStep:recommendations.length ? Math.min(...recommendations.map(item=>preferenceAdvice[item.field][0])) : 0,recommendations});
  }
  return recovery('We couldn’t build this trip.', 'We could not confirm why planning stopped. Your trip details have not been identified as a problem. You can try again, or review the details without changing them.', {code:'REQUEST_FAILED'});
}
