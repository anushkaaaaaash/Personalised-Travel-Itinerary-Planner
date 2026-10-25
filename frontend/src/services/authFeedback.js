// Fixed messages only: never display backend/provider bodies or account-specific details.
export function authFailure(status, diagnostic = {}) {
  if (diagnostic.kind === 'network') return 'The account service could not be reached. Check your connection and whether this site address is allowed by the backend. This does not establish that your password or email confirmation is wrong.';
  if (diagnostic.kind === 'invalid_json') return 'The account service returned an unreadable response. Account access could not be verified.';
  if (status === 503) return 'Account access is not configured. Check the backend setup.';
  if (status === 429) return 'Too many attempts. Please wait before retrying.';
  if (status === 504) return 'Account request timed out. Please retry when ready.';
  if (status === 401) return 'Sign-in could not be verified. Check your details and any required email confirmation. If your session expired, sign in again.';
  if (status === 403) return 'Account access was blocked. This site address or request may not be permitted.';
  if (status === 400 || status === 422) return 'Check the account form details before submitting again.';
  return 'The account service could not complete the request. Please try again later.';
}
