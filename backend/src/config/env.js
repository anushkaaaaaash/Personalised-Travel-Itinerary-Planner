const path = require('path');

// Load only this backend's local file, regardless of the shell's working folder.
require('dotenv').config({ path: path.join(__dirname, '../../.env') });

const env = {
  host: process.env.HOST || '127.0.0.1',
  port: Number(process.env.PORT) || 5000,
  nodeEnv: process.env.NODE_ENV || 'development',
  clientOrigin: process.env.CLIENT_ORIGIN || 'http://localhost:5173',
  openaiApiKey: process.env.OPENAI_API_KEY || '',
  mapsApiKey: process.env.MAPS_API_KEY || '',
  supabaseUrl: process.env.SUPABASE_URL || '',
  supabaseSecretKey: process.env.SUPABASE_SECRET_KEY || '',
};

module.exports = { env };
