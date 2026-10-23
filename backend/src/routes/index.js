const { Router } = require('express');
const healthController = require('../controllers/healthController');

const { createTripController } = require('../controllers/tripController');

function createRouter({ saveTrip }) {
  const router = Router();
  router.get('/health', healthController.getHealth);
  router.post('/trips', createTripController({ saveTrip }));
  return router;
}

module.exports = { createRouter };
