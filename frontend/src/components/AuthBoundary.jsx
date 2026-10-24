import { useEffect, useRef, useState } from 'react';
import { requestJson, PlannerRequestError } from '../services/readRequest.js';
import { getSession, setSession, subscribeSession } from '../services/session.js';
import PlannerRoutes from './PlannerRoutes.jsx';
const failure = status => status === 503 ? 'Account access is not configured. Check the backend setup.' : status === 429 ? 'Too many attempts. Please wait before retrying.' : status === 504 ? 'Account request timed out. Please retry when ready.' : 'Account request failed. Check your details or confirm your email, then retry.';
export default function AuthBoundary() {
  const [config, setConfig] = useState(null), [configError, setConfigError] = useState('');
  const [session, updateSession] = useState(getSession), [epoch, setEpoch] = useState(0);
  const [mode, setMode] = useState('login'), [email, setEmail] = useState(''), [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  const active = useRef(null), mounted = useRef(true);
  useEffect(() => { mounted.current = true; const unsubscribe = subscribeSession(value => { updateSession(value); setEpoch(n => n + 1); setPassword(''); }); return () => { mounted.current = false; active.current?.abort(); unsubscribe(); }; }, []);
  async function loadConfig() {
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    setConfigError('');
    try {
      const value = await requestJson('/auth/config', { signal: controller.signal, failure });
      if (!value || typeof value.enabled !== 'boolean' || !['local', 'production'].includes(value.mode) || typeof value.ownership_enabled !== 'boolean') throw new PlannerRequestError('Account configuration could not be verified.');
      if (mounted.current && !controller.signal.aborted) setConfig(value);
    } catch (e) { if (mounted.current && !controller.signal.aborted) setConfigError(e instanceof PlannerRequestError ? e.message : 'Account configuration unavailable.'); }
    finally { if (active.current === controller) active.current = null; }
  }
  useEffect(() => { void loadConfig(); }, []);
  async function submit(event) {
    event.preventDefault(); if (active.current) return;
    const controller = new AbortController(); active.current = controller;
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await requestJson(`/auth/${mode === 'login' ? 'login' : 'register'}`, { method: 'POST', payload: { email: email.trim(), password }, signal: controller.signal, failure });
      if (controller.signal.aborted || !mounted.current) return;
      if (value.session) {
        const s = value.session;
        if (typeof s.access_token !== 'string' || !s.access_token || s.token_type !== 'bearer' || !Number.isFinite(s.expires_at) || s.expires_at * 1000 <= Date.now() || !value.user?.id) throw new PlannerRequestError('Account session could not be verified.');
        setSession({ ...s, user: value.user }); setNotice('Signed in. Session stays in memory and ends on refresh or expiry.');
      } else if (value.pending_confirmation === true) setNotice('Check your email for any required confirmation, then sign in. This response does not confirm a new account or verified email.');
      else throw new PlannerRequestError('No active session was returned. Confirm your email and try signing in.');
    } catch (e) { if (!controller.signal.aborted && mounted.current) setError(e instanceof PlannerRequestError ? e.message : 'Account request could not be completed.'); }
    finally { if (active.current === controller) { active.current = null; if (mounted.current) { setBusy(false); setPassword(''); } } }
  }
  async function logout() {
    if (active.current) return;
    const controller = new AbortController(); active.current = controller; setBusy(true); setError('');
    // Start revocation with the existing token, then clear local data immediately.
    const pending = requestJson('/auth/logout', { method: 'POST', payload: {}, signal: controller.signal, failure });
    setSession(null); setNotice('Signed out on this device.');
    try { await pending; } catch { if (mounted.current) setNotice('Local session cleared. Server sign-out could not be confirmed; the previous session may remain active until expiry.'); }
    finally { if (active.current === controller) { active.current = null; if (mounted.current) setBusy(false); } }
  }
  if (!config) return <main className="page"><section className="card"><h1>Travel planner</h1>{configError ? <><p role="alert">{configError}</p><button className="preview-btn" onClick={loadConfig}>Retry connection</button></> : <p role="status">Checking planner configuration…</p>}</section></main>;
  const allowed = (config.mode === 'local' && !config.ownership_enabled) || (config.ownership_enabled && Boolean(session));
  return <>
    <aside className="account-shell card" aria-label="Account access"><h2>{config.mode === 'local' ? 'Private local planner' : 'Your planner account'}</h2>
      <p className="hint">{config.mode === 'local' && !config.ownership_enabled ? 'Local mode is for one trusted operator. Legacy preference-only history is project-wide. My saved full itineraries uses separate account-scoped storage. Public deployment is not configured.' : 'Account access is required. Sessions are kept in memory only.'}</p>
      {config.mode === 'production' && !config.ownership_enabled && <p role="alert">Planner access is blocked until owner-scoped storage is configured.</p>}
      {config.enabled && (session ? <div><p>Signed in as {session.user.email || 'your account'}</p><button className="preview-btn" onClick={logout} disabled={busy}>Sign out and clear planner</button></div> : <details open={config.mode === 'production' || config.ownership_enabled}><summary>Sign in or register</summary><form onSubmit={submit} className="account-form"><label className="field">Email<input type="email" required autoComplete="email" value={email} onChange={e => setEmail(e.target.value)} disabled={busy} /></label><label className="field">Password<input type="password" required minLength={8} maxLength={128} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /></label><button className="generate-btn" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Register account'}</button><button type="button" className="preview-btn" disabled={busy} onClick={() => { setMode(m => m === 'login' ? 'register' : 'login'); setError(''); setNotice(''); setPassword(''); }}>{mode === 'login' ? 'Switch to registration' : 'Switch to sign in'}</button></form></details>)}
      {!config.enabled && <p className="hint">Account registration and sign-in are not configured.</p>}
      {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    </aside>
    {allowed && <PlannerRoutes key={epoch} ownershipEnabled={config.ownership_enabled} signedIn={Boolean(session)} />}
  </>;
}
