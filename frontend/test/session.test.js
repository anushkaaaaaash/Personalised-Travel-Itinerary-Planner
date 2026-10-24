import test from 'node:test';
import assert from 'node:assert/strict';
import { getSession, setSession, sessionFetch, subscribeSession } from '../src/services/session.js';
test('memory session adds bearer token and clears on unauthorized response', async () => {
  const original = globalThis.fetch; const changes = []; const unsubscribe = subscribeSession(s => changes.push(s));
  try {
    setSession({ access_token: 'fixture-token', expires_at: Date.now() / 1000 + 60 });
    globalThis.fetch = async (_, options) => { assert.equal(options.headers.Authorization, 'Bearer fixture-token'); return { status: 401 }; };
    await sessionFetch('/api/trips', { headers: { Accept: 'application/json' } });
    assert.equal(getSession(), null); assert.equal(changes.at(-1), null);
  } finally { globalThis.fetch = original; setSession(null); unsubscribe(); }
});
test('an older request cannot clear a newer login', async () => {
  const original = globalThis.fetch; let finish;
  try {
    setSession({ access_token: 'old', expires_at: Date.now() / 1000 + 60 });
    globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
    const pending = sessionFetch('/api/trips');
    setSession({ access_token: 'new', expires_at: Date.now() / 1000 + 60 }); finish({ status: 401 }); await pending;
    assert.equal(getSession().access_token, 'new');
  } finally { globalThis.fetch = original; setSession(null); }
});
test('expiry clears memory and notifies planner reset subscribers', async () => {
  setSession({ access_token: 'fixture', expires_at: Date.now() / 1000 + 0.01 });
  await new Promise(r => setTimeout(r, 30)); assert.equal(getSession(), null);
});
