// Session credentials live only in memory, never in browser storage or exports.
let session = null;
let timer = null;
const listeners = new Set();
const publish = () => { for (const listener of listeners) listener(session); };
export const getSession = () => session;
export function setSession(value) {
  clearTimeout(timer); session = value; publish();
  if (value) timer = setTimeout(() => setSession(null), Math.max(0, value.expires_at * 1000 - Date.now()));
}
export function subscribeSession(listener) { listeners.add(listener); return () => listeners.delete(listener); }
export async function sessionFetch(url, options = {}) {
  const current = session;
  const response = await globalThis.fetch(url, { ...options, headers: { ...options.headers, ...(current ? { Authorization: `Bearer ${current.access_token}` } : {}) } });
  if (response.status === 401 && current && current === session) setSession(null);
  return response;
}
