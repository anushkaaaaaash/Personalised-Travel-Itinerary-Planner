// The frontend and backend use the same validation rules, without sharing secrets.
const tripPreferences = import('../../../shared/tripPreferences.mjs');

function isConfirmedId(id) {
  return (
    (typeof id === 'string' && id.length > 0 && id.length <= 200
      && id === id.trim() && !/[\u0000-\u001f\u007f]/.test(id)) ||
    (Number.isSafeInteger(id) && id > 0)
  );
}

function createTripController({ saveTrip }) {
  return async function createTrip(req, res) {
    if (!req.is('application/json')) {
      return res.status(415).json({
        error: { code: 'UNSUPPORTED_MEDIA_TYPE', message: 'Send preferences as JSON.' },
      });
    }

    try {
      const { validateTripPreferences } = await tripPreferences;
      const result = validateTripPreferences(req.body);
      if (!result.valid) {
        return res.status(400).json({
          error: {
            code: 'VALIDATION_ERROR',
            message: 'Check the trip preferences and try again.',
            fields: result.errors,
          },
        });
      }

      // The storage adapter must confirm a persisted row, not manufacture an ID.
      const savedTrip = await saveTrip(result.value);
      if (!savedTrip || !isConfirmedId(savedTrip.id)) {
        return res.status(500).json({
          error: {
            code: 'TRIP_SAVE_UNCONFIRMED',
            message: 'The save could not be confirmed. Check stored trips before retrying.',
          },
        });
      }
      return res.status(201).json({ trip: { id: savedTrip.id } });
    } catch (error) {
      if (error && error.code === 'TRIP_STORAGE_NOT_CONFIGURED') {
        return res.status(503).json({
          error: {
            code: 'TRIP_STORAGE_NOT_CONFIGURED',
            message: 'Trip saving is not configured yet. Your preferences have not been saved.',
          },
        });
      }
      return res.status(500).json({
        error: {
          code: 'TRIP_SAVE_FAILED',
          message: 'The save could not be confirmed. Check stored trips before retrying.',
        },
      });
    }
  };
}

module.exports = { createTripController };
