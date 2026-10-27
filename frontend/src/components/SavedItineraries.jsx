import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { createSavedOperation, createPendingSaveRecovery, snapshot } from '../services/savedItineraries.js';
export default function SavedItineraries({ signedIn=false, preferences, itinerary, plannerBusy=false, onLoad }) {
  const [state,setState]=useState({busy:false,error:''}), [title,setTitle]=useState('');
  const [page,setPage]=useState(null), [selected,setSelected]=useState(null), [confirm,setConfirm]=useState(null);
  const [notice,setNotice]=useState(''), [pending,setPending]=useState(null);
  const operation=useRef(null), current=useRef(null);
  const recovery=useRef(null);
  if(!recovery.current)recovery.current=createPendingSaveRecovery();
  const fingerprint=JSON.stringify({preferences,itinerary});
  current.current={fingerprint,plannerBusy};
  useEffect(()=>{const controller=createSavedOperation(setState);operation.current=controller;return()=>{controller.dispose();recovery.current.dispose();};},[]);
  useEffect(()=>{setConfirm(null);},[fingerprint,title]);
  const busy=plannerBusy || state.busy;
  async function loadPage(offset=0) {
    if(busy || operation.current?.busy())return;
    setConfirm(null);setNotice('');
    const outcome=await operation.current.run({action:'list',offset});
    if(outcome.result)setPage(outcome.result);
  }
  async function load(id) {
    if(busy || operation.current?.busy())return;
    const started=fingerprint; setConfirm(null);
    const outcome=await operation.current.run({action:'load',id});
    if(!outcome.result)return;
    if(current.current.fingerprint!==started || current.current.plannerBusy){setNotice('The editor changed while loading. Load again when ready; your current plan was kept.');return;}
    setSelected(outcome.result);setTitle(outcome.result.title);
    onLoad(outcome.result);setNotice('Your trip is ready to explore.');
  }
  async function checkPending() {
    if(busy || operation.current?.busy())return;
    const original=recovery.current.view();
    if(!original)return;
    setConfirm(null);
    const outcome=await operation.current.run({action:'load',id:original.id});
    const resolution=recovery.current.reconcile(original.id,outcome,{checked:true});
    if(resolution.ignored)return;
    const remaining=recovery.current.view();setPending(remaining);
    if(resolution.resolved){setPage(null);setNotice('The original save is confirmed. Your current editor and selected record were not changed. Load saved history to open that snapshot.');}
    else if(remaining?.retryAllowed)setNotice('The original save was not found. You may explicitly retry the original snapshot with the same save ID. Current edits will not be included.');
    else setNotice('The original save is still unconfirmed. Check again before retrying; your current editor and selected record are unchanged.');
  }
  function prepare(action) {
    if(busy || operation.current?.busy())return;
    try {
      const record=snapshot(title,preferences,itinerary);
      setConfirm({action,record,fingerprint});setNotice('');
    } catch {setNotice('Enter a title and a complete valid itinerary with matching preferences before saving.');}
  }
  async function commit() {
    if(!confirm || busy || operation.current?.busy() || confirm.fingerprint!==fingerprint)return;
    const action=confirm.action, retrying=action==='retry';
    let request;
    if(retrying){try{request=recovery.current.retry();}catch{return;}}
    const id=retrying?request.id:action==='create'?crypto.randomUUID():selected?.id;
    if(!id)return;
    if(action==='create')recovery.current.begin(id,confirm.record);
    if(action==='create'||retrying)setPending(recovery.current.view());
    const outcome=await operation.current.run(request || {action,id,record:confirm.record,expectedVersion:selected?.version});
    if(outcome.ignored)return;
    let resolution;
    if(action==='create'||retrying){resolution=recovery.current.reconcile(id,outcome,{initial:action==='create'});setPending(recovery.current.view());}
    setConfirm(null);
    if(resolution?.rejected){setNotice('The save was rejected before storage. Your local plan is retained. Correct the plan or shorten its text, then explicitly choose Save new again.');return;}
    if(!outcome.result){setNotice(action==='create'||retrying?'Save outcome uncertain. Use Check pending save before creating another copy.':'Your local plan is retained. Reload the saved record before another update or delete.');return;}
    if(retrying){setPage(null);setNotice('The original snapshot is saved. Your current editor and selected record were not changed. Load saved history to open it.');return;}
    if(action==='delete'){setSelected(null);setPage(null);setNotice('Saved record deleted. The open local plan was retained.');}
    else {setSelected(outcome.result);setPage(null);setNotice('Your trip is saved.');}
  }
  return <section className="card saved-trips" aria-label="Saved trips"><h2>Your saved trips</h2>
    <p>Keep your favorite plans together.</p>
    {!signedIn?<p>Sign in to keep your trips in one place.</p>:<>
      {itinerary && <label className="field">Trip name<input maxLength={120} value={title} placeholder="A week to remember" onChange={e=>setTitle(e.target.value)} disabled={state.busy}/></label>}
      {selected && <p>{selected.title} · version {selected.version}</p>}
      <div className="step-actions">{itinerary && <button className="preview-btn" disabled={busy || Boolean(pending)} onClick={()=>prepare('create')}>Save this trip</button>}
      {selected && itinerary && <button className="preview-btn" disabled={busy} onClick={()=>prepare('update')}>Save changes</button>}
      {selected && <button className="preview-btn" disabled={busy} onClick={()=>setConfirm({action:'delete',fingerprint})}>Delete trip</button>}
      <button className="preview-btn" disabled={busy} onClick={()=>loadPage()}>Browse saved trips</button>
      {pending && <button className="preview-btn" disabled={busy} onClick={checkPending}>Check pending save</button>}
      {pending?.retryAllowed && <button className="preview-btn" disabled={busy} onClick={()=>setConfirm({action:'retry',fingerprint})}>Retry original save</button>}</div>
      {confirm && <div role="group" aria-label="Confirm saved itinerary operation"><p>{confirm.action==='retry'?'Retry the original snapshot with its original save ID? Current editor changes will not be saved by this retry.':confirm.action==='delete'?'Delete this trip from your collection? This cannot be undone.':confirm.action==='update'?'Save these changes to your trip?':'Save this trip to your collection?'}</p><button disabled={busy} onClick={commit}>Confirm {confirm.action}</button><button disabled={state.busy} onClick={()=>setConfirm(null)}>Cancel</button></div>}
      {page && <><ul>{page.items.map(item=><li key={item.id}>{item.title} · revision {item.version} · {item.updatedAt} <button disabled={busy} onClick={()=>load(item.id)}>Load for editing</button> <Link to={`/itineraries/${item.id}`} onClick={e=>{if(busy||!window.confirm('Leave your current edits and open this saved trip?'))e.preventDefault();}}>View details and share</Link></li>)}</ul>{!page.items.length && <p>Your next adventure belongs here. Save a trip to start your collection.</p>}<button disabled={busy || page.offset===0} onClick={()=>loadPage(Math.max(0,page.offset-20))}>Previous saved page</button><button disabled={busy || !page.hasMore} onClick={()=>loadPage(page.offset+20)}>Next saved page</button></>}
    </>}
    {state.busy && <p role="status">Saving your changes…</p>}{state.error && <p role="alert">{state.error}</p>}{notice && <p role="status">{notice}</p>}
  </section>;
}
