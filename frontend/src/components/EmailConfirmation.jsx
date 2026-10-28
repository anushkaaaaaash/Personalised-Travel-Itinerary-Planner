import { useEffect, useRef } from 'react';
import { Check, Mail, ArrowRight, CircleAlert } from 'lucide-react';
import SiteHeader from './SiteHeader.jsx';

export default function EmailConfirmation({ status, onContinue, signedIn = false }) {
  const heading = useRef(null);
  const verified = status === 'verified';
  const checking = status === 'checking';
  const unavailable = status === 'unavailable';
  useEffect(() => { heading.current?.focus(); }, [status]);
  return <div className="page confirmation-page"><SiteHeader/>
    <main className={`card email-confirmation email-confirmation--${status}`} aria-busy={checking}>
      <div className="email-confirmation__seal" aria-hidden="true">{verified ? <Check size={35} strokeWidth={1.7}/> : checking ? <Mail size={33} strokeWidth={1.5}/> : <CircleAlert size={33} strokeWidth={1.5}/>}</div>
      <p className="eyebrow">{verified ? 'A lovely place to begin' : 'Your travel planner account'}</p>
      <h1 ref={heading} tabIndex={-1}>{checking ? 'Checking your confirmation…' : verified ? 'Email confirmed. You’re all set.' : unavailable ? 'We couldn’t check your confirmation.' : 'This link couldn’t be verified.'}</h1>
      <p role="status">{checking ? 'Just a moment while we securely check your email confirmation.' : verified ? 'Your email address is verified. Your next adventure is one step closer.' : unavailable ? 'The connection may have been interrupted. Your email may already be confirmed. Try signing in, or reopen the link from your confirmation email.' : 'This confirmation link may be expired, already used, or incomplete. If you already confirmed your email, try signing in. Otherwise, use the latest confirmation email.'}</p>
      {!checking && <button className="generate-btn" type="button" onClick={onContinue}>{signedIn ? 'Continue to your travel space' : 'Continue to sign in'}<ArrowRight size={17} aria-hidden="true"/></button>}
      {verified && !signedIn && <p className="hint">Sign in with the email and password you chose when you registered.</p>}
      {!verified && !checking && <p className="hint">Still stuck? Return to sign in to check your account. Use the latest confirmation email if you still need to confirm your address.</p>}
    </main>
  </div>;
}
