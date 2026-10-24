import { RecommendationError } from './recommendations.js';
const empty = () => ({ loading: false, error: '', result: null });
export function createRecommendationRequest({ generate, onStateChange }) {
  let active = null;
  let disposed = false;
  const publish = (state) => { if (!disposed) onStateChange(state); };
  return {
    isBusy: () => Boolean(active),
    reset() { active?.abort(); active = null; publish(empty()); },
    async submit(payload) {
      if (disposed || active) return { ignored: true };
      const controller = new AbortController(); active = controller;
      publish({ loading: true, error: '', result: null });
      try {
        const result = await generate(payload, { signal: controller.signal });
        if (disposed || controller.signal.aborted || active !== controller) return { ignored: true };
        publish({ loading: false, error: '', result });
        return { result };
      } catch (error) {
        if (disposed || controller.signal.aborted || active !== controller) return { ignored: true };
        const message = error instanceof RecommendationError ? error.message : 'AI recommendations could not be verified. Please try again later.';
        publish({ loading: false, error: message, result: null }); return { error: message };
      } finally { if (active === controller) active = null; }
    },
    dispose() { disposed = true; active?.abort(); active = null; },
  };
}
