import {useEffect,useRef,useState} from 'react';
import {Link} from 'react-router-dom';
import {createSavedAdaptiveClient} from '../services/savedAdaptiveTrips.js';
import {getSession,subscribeSession} from '../services/session.js';

export default function SavedAdaptiveTrips({client}) {
  const fallback=useRef(null);if(!fallback.current)fallback.current=createSavedAdaptiveClient();
  const api=client || fallback.current,scope=useRef(null);
  const [state,setState]=useState({page:null,busy:false,error:'',signedOut:false,retryOffset:0});
  async function load(offset=0) {
    const current=scope.current;
    if(!current||current.disposed||current.active||getSession()!==current.session)return;
    const controller=new AbortController();current.active=controller;
    setState(previous=>({...previous,busy:true,error:'',retryOffset:offset}));
    try {
      const page=await api.list(offset,{signal:controller.signal});
      if(scope.current===current&&!current.disposed&&!controller.signal.aborted&&getSession()===current.session)setState({page,busy:false,error:'',signedOut:false,retryOffset:offset});
    } catch {
      if(scope.current===current&&!current.disposed&&!controller.signal.aborted&&getSession()===current.session)setState(previous=>({...previous,busy:false,error:'Your complete saved trips could not be checked. Try again; no saved trip has been changed.'}));
    } finally {if(current.active===controller)current.active=null;}
  }
  useEffect(()=>{
    const session=getSession();
    if(!session?.user?.id){setState({page:null,busy:false,error:'',signedOut:true,retryOffset:0});return;}
    const current={session,active:null,disposed:false};scope.current=current;
    const unsubscribe=subscribeSession(next=>{if(next!==session){current.disposed=true;current.active?.abort();setState({page:null,busy:false,error:'',signedOut:true,retryOffset:0});}});
    void load(0);
    return()=>{current.disposed=true;current.active?.abort();unsubscribe();if(scope.current===current)scope.current=null;};
  },[api]);
  const {page,busy,error,signedOut}=state;
  return <section className="card saved-trips" aria-label="Your complete saved trips">
    <h2>Your complete saved trips</h2>
    <p>Completed trip versions you explicitly saved to your account, separate from temporary planning sessions.</p>
    {signedOut?<p role="status">Sign in again to browse saved trips for your account.</p>:<>
      {busy&&<p role="status">Loading saved section-by-section trips…</p>}
      {error&&<><p role="alert">{error}</p><button className="preview-btn" disabled={busy} onClick={()=>load(state.retryOffset)}>Check saved section-by-section trips</button></>}
      {page&&<>
        {page.items.length?<ul className="saved-trip-list">{page.items.map(item=><li key={item.id}>
          <h3><Link to={`/saved-adaptive-trips/${item.id}`}>{item.title}</Link></h3>
          <p>{item.destination} · {item.totalDays} days · <time dateTime={item.startDate}>{item.startDate}</time> to <time dateTime={item.endDate}>{item.endDate}</time></p>
          <p className="hint">Saved <time dateTime={item.createdAt}>{new Date(item.createdAt).toLocaleDateString()}</time> · Account copy, not a 24-hour checkpoint.</p>
        </li>)}</ul>:<p>No section-by-section trips have been saved to this account yet.</p>}
        <nav className="step-actions" aria-label="Saved section-by-section trip pages">
          <button className="preview-btn" disabled={busy||page.offset===0} onClick={()=>load(Math.max(0,page.offset-20))}>Previous trips</button>
          <button className="preview-btn" disabled={busy||!page.hasMore||page.offset>=10000} onClick={()=>load(page.offset+20)}>Next trips</button>
        </nav>
      </>}
    </>}
  </section>;
}
