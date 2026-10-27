import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import SiteHeader from '../components/SiteHeader.jsx';
import { createSavedOperation } from '../services/savedItineraries.js';
import { getSession, subscribeSession } from '../services/session.js';
import { useDestinationTheme } from '../themes/DestinationTheme.jsx';

export default function SavedTripsPage() {
  const [state,setState]=useState({busy:false,error:''}),[page,setPage]=useState(null),[signedOut,setSignedOut]=useState(false);
  const operation=useRef(null);
  useDestinationTheme('');
  async function loadPage(offset=0) {
    const active=operation.current;
    if(!active || active.session!==getSession() || active.controller.busy())return;
    const result=await active.controller.run({action:'list',offset});
    if(operation.current===active && active.session===getSession() && result.result)setPage(result.result);
  }
  useEffect(()=>{
    const session=getSession();
    if(!session?.user?.id){setSignedOut(true);return;}
    const active={session,controller:createSavedOperation(next=>{if(getSession()===session)setState(next);})};
    operation.current=active;void loadPage();
    const unsubscribe=subscribeSession(next=>{if(next!==session){active.controller.dispose();operation.current=null;setPage(null);setState({busy:false,error:''});setSignedOut(true);}});
    return()=>{unsubscribe();active.controller.dispose();if(operation.current===active)operation.current=null;};
  },[]);
  return <main className="page">
    <SiteHeader showSavedTrips/>
    <Link to="/">← Back to planner & unfinished trip</Link>
    <section className="card saved-trips" aria-labelledby="saved-trips-title">
      <h1 id="saved-trips-title">Your saved trips</h1>
      <p>Plans you explicitly saved to your account. Unfinished 24-hour plans are separate—return to the planner to open them.</p>
      {signedOut?<p role="status">Sign in to browse your saved trips.</p>:<>
        {state.busy&&<p role="status">Loading saved trips…</p>}
        {state.error&&<p role="alert">{state.error}</p>}
        {!state.busy&&state.error&&<button className="preview-btn" onClick={()=>loadPage(page?.offset || 0)}>Retry loading saved trips</button>}
        {page&&<>
          {page.items.length?<ul className="saved-trip-list">{page.items.map(item=><li key={item.id}>
            <h2><Link to={`/itineraries/${item.id}`}>{item.title}</Link></h2>
            <p className="hint">Saved revision {item.version} · Updated <time dateTime={item.updatedAt}>{new Date(item.updatedAt).toLocaleDateString()}</time></p>
          </li>)}</ul>:<p>No account-saved trips yet. A temporary unfinished plan will not appear in this collection.</p>}
          <nav className="step-actions" aria-label="Saved trip pages"><button className="preview-btn" disabled={state.busy||page.offset===0} onClick={()=>loadPage(Math.max(0,page.offset-20))}>Previous saved page</button><button className="preview-btn" disabled={state.busy||!page.hasMore||page.offset>=10000} onClick={()=>loadPage(page.offset+20)}>Next saved page</button></nav>
        </>}
      </>}
    </section>
  </main>;
}
