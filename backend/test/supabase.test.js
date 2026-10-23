const assert = require('node:assert/strict');
const test = require('node:test');
const { createSupabaseProvider } = require('../src/config/supabase');

test('creating a Supabase provider does not create a client', () => {
  let calls = 0;
  createSupabaseProvider({ config: {}, clientFactory: () => { calls += 1; } });
  assert.equal(calls, 0);
  assert.equal(Object.keys(require.cache).some((key) => key.includes('@supabase/supabase-js')), false);
});

test('missing backend configuration throws a safe error only when requested', () => {
  let calls = 0;
  const getClient = createSupabaseProvider({ config: {}, clientFactory: () => { calls += 1; } });
  assert.throws(getClient, (error) => error.code === 'TRIP_STORAGE_NOT_CONFIGURED');
  assert.equal(calls, 0);
});

test('a local fake factory is initialized once with server-only session settings', () => {
  const calls = [];
  const fakeClient = { localFake: true };
  const getClient = createSupabaseProvider({
    config: { supabaseUrl: 'https://example.invalid', supabaseSecretKey: 'fake-test-value' },
    clientFactory: (...args) => { calls.push(args); return fakeClient; },
  });
  assert.equal(getClient(), fakeClient);
  assert.equal(getClient(), fakeClient);
  assert.deepEqual(calls, [[
    'https://example.invalid', 'fake-test-value',
    { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } },
  ]]);
});
