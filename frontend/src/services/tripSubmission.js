import { TripApiError, isConfirmedTripId } from './api.js';

const emptyState = () => ({ loading: false, error: '', savedTrip: null });

/** A single in-flight save, with teardown safety for navigation/unmount. */
export function createTripSubmission({ saveTrip, onStateChange }) {
  let active = null;
  let disposed = false;
  let state = emptyState();
  function publish(next) {
    state = next;
    if (!disposed) onStateChange(next);
  }
  return {
    isBusy() { return Boolean(active); },
    reset() {
      if (!disposed && !active) publish(emptyState());
    },
    async submit(payload) {
      // This synchronous lock also catches repeat clicks before React rerenders.
      if (disposed || active || state.savedTrip) return { ignored: true };
      const controller = new AbortController();
      active = controller;
      publish({ loading: true, error: '', savedTrip: null });
      try {
        const savedTrip = await saveTrip(payload, { signal: controller.signal });
        if (disposed || controller.signal.aborted) return { ignored: true };
        if (!savedTrip || !isConfirmedTripId(savedTrip.id)) throw new Error('Unconfirmed save');
        publish({ loading: false, error: '', savedTrip });
        return { savedTrip };
      } catch (error) {
        if (disposed || controller.signal.aborted) return { ignored: true };
        const message = error instanceof TripApiError
          ? error.message
          : 'We could not confirm your preferences were saved. Please check before trying again.';
        publish({ loading: false, error: message, savedTrip: null });
        return { error: message };
      } finally {
        if (active === controller) active = null;
      }
    },
    dispose() {
      disposed = true;
      active?.abort();
      active = null;
    },
  };
}
