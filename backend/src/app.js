const express = require('express');
const cors = require('cors');
const { env } = require('./config/env');
const { createRouter } = require('./routes');
const tripService = require('./services/tripService');

// Importing this module never opens a port or initializes a database client.
function createApp({ saveTrip = tripService.saveTrip, config = env } = {}) {
  const app = express();
  app.disable('x-powered-by');
  app.use(cors({ origin: config.clientOrigin }));
  app.use(express.json({ limit: '16kb', strict: true }));
  app.use('/api', createRouter({ saveTrip }));

  app.use((_req, res) => {
    res.status(404).json({ error: { code: 'NOT_FOUND', message: 'Endpoint not found.' } });
  });

  // Do not expose parser input, database details, secrets, or stack traces.
  app.use((error, _req, res, _next) => {
    if (error.type === 'entity.too.large') {
      return res.status(413).json({
        error: { code: 'PAYLOAD_TOO_LARGE', message: 'The request is too large.' },
      });
    }
    if (error.type === 'entity.parse.failed') {
      return res.status(400).json({
        error: { code: 'INVALID_JSON', message: 'Send a valid JSON object.' },
      });
    }
    if (error.status === 415) {
      return res.status(415).json({
        error: { code: 'UNSUPPORTED_MEDIA_TYPE', message: 'Use UTF-8 JSON for this request.' },
      });
    }
    return res.status(500).json({
      error: { code: 'INTERNAL_ERROR', message: 'The request could not be completed.' },
    });
  });

  return app;
}

module.exports = { createApp };
