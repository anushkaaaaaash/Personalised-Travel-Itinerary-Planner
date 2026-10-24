const { env } = require('./env');

// Lazy initialization keeps /api/health usable with no database configuration.
// The optional factory is for local tests; it never requires real credentials.
function createSupabaseProvider({ config = env, clientFactory } = {}) {
  let client;

  return function getSupabase() {
    if (client) return client;

    if (!config.supabaseUrl || !config.supabaseSecretKey) {
      const error = new Error('Trip storage has not been configured.');
      error.code = 'TRIP_STORAGE_NOT_CONFIGURED';
      throw error;
    }

    const createClient = clientFactory || require('@supabase/supabase-js').createClient;
    client = createClient(config.supabaseUrl, config.supabaseSecretKey, {
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    });
    return client;
  };
}

const getSupabase = createSupabaseProvider();

module.exports = { getSupabase, createSupabaseProvider };
