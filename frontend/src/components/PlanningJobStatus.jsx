import DestinationLoading from './DestinationLoading.jsx';
import { jobMessage } from '../services/planningJobs.js';
export default function PlanningJobStatus({ state, destination, onCheck, onCancel, onNewPlan }) {
  const status=state.job?.status;
  const terminal=['failed','cancelled','expired'].includes(status);
  const uncertain=state.needsCheck || status==='submission_unknown';
  if(state.rejected)return <section className="card results-hero"><p className="eyebrow">A little adjustment</p><h2>Let’s check your trip details.</h2><p role="alert">{state.error}</p><button className="generate-btn" onClick={onNewPlan}>Back to trip preferences</button></section>;
  if(terminal)return <section className="card results-hero"><p className="eyebrow">Your travel plans</p><h2>{status==='cancelled'?'A pause, not goodbye.':status==='expired'?'Ready for a fresh start?':'Let’s try a fresh plan.'}</h2><p role="status">{state.error || jobMessage(state.job)}</p><button className="generate-btn" onClick={onNewPlan}>Back to trip preferences</button></section>;
  if(uncertain || state.error)return <section className="card results-hero"><p className="eyebrow">Keeping your place</p><h2>Let’s check on your trip.</h2><p role="status">{state.cancelling ? 'Stopping your plan…' : state.error || 'We’re checking whether your plan has started.'}</p><div className="step-actions"><button className="generate-btn" disabled={state.checking || state.cancelling} onClick={onCheck}>Check my plan</button>{state.job?.id && <button className="preview-btn" disabled={state.checking || state.cancelling} onClick={onCancel}>{status==='submission_unknown'?'Stop planning':'Cancel planning'}</button>}</div><p className="hint">We’ll check this same plan before starting another.</p></section>;
  return <DestinationLoading destination={state.preferences?.destination || destination} title={status==='queued'?'Your next chapter is in line.':'Your trip is taking shape'} status={state.cancelling?'Stopping your plan…':status?jobMessage(state.job):state.resumable?'Picking up your trip…':'Starting your trip plan…'} onCancel={state.cancelling?undefined:onCancel} cancelLabel="Cancel planning"/>;
}
