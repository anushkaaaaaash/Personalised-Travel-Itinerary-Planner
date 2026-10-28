import {tripDayLabel,visibleDayRange} from '../utils/dayLabels.js';
import SavedTripPdfButton from '../components/SavedTripPdfButton.jsx';
import {useEffect,useRef,useState} from 'react';
import {Link,useParams} from 'react-router-dom';
import SiteHeader from '../components/SiteHeader.jsx';
import {createSavedAdaptiveClient} from '../services/savedAdaptiveTrips.js';
import {readContinuousDays,continuousDaysMessage} from '../services/continuousTripDays.js';
import {getSession,subscribeSession} from '../services/session.js';
import {COST_LABELS} from '../services/itineraries.js';
import {researchSourceUrl} from '../services/groundedPlanning.js';
import {useDestinationTheme} from '../themes/DestinationTheme.jsx';

const money=(currency,value)=>{const cents=BigInt(value);return`${currency} ${(cents/100n).toLocaleString()}.${String(cents%100n).padStart(2,'0')}`;};

function HistoricalSources({section}) {
  if(section.sourceAssociation==='none_recorded')return <p className="hint">No sources were saved for these dates. Confirm travel details before booking.</p>;
  return <details className="practical-checks"><summary>Saved sources for these dates</summary>
    <p>These saved notes are historical, unverified observations. Saving did not refresh them or verify prices, hours, routes or availability.</p>
    {section.historicalSources.map((notes,index)=><section key={index} aria-label={`Historical source notes ${index+1}`}>
      <p className="hint">Notes received <time dateTime={notes.receivedAt}>{new Date(notes.receivedAt).toLocaleString()}</time>. This is the planner’s receipt time, not a publisher’s update date.</p>
      <p className="hint">Original freshness-window end: <time dateTime={notes.expiresAt}>{new Date(notes.expiresAt).toLocaleString()}</time>. This is not a fresh check; confirm important details before booking.</p>
      <p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{notes.text}</p>
      <ul>{notes.sources.map((source,i)=>{const href=researchSourceUrl(source.url);return <li key={`${source.url}-${i}`} style={{overflowWrap:'anywhere'}}>{href?<a href={href} target="_blank" rel="noopener noreferrer">{source.title || new URL(href).hostname}</a>:<span>Source link unavailable</span>}</li>;})}</ul>
    </section>)}
  </details>;
}
function SavedSection({section,currency,tripStart}) {
  const itinerary=section.checkpoint.itinerary;
  return <section className="adaptive-day-group" aria-label={`Saved trip days ${section.startDate} to ${section.endDate}`}>
    {itinerary.days.map((day,index)=><details className="card adaptive-day" key={day.date}>
      <summary><strong>{tripDayLabel(day.date,tripStart)}</strong> · <time dateTime={day.date}>{day.date}</time> · {day.mainActivityCount} main activities</summary>
      <ol className="activity-list timeline">{day.activities.map(activity=><li key={activity.id}>
        <div className="activity-meta"><time>{activity.startTime}</time><span>{activity.durationMinutes} min</span>{activity.fixedTime&&<span className="tag">Fixed time</span>}</div><strong>{activity.title}</strong><p>{activity.notes}</p>
      </li>)}</ol>
      <div className="day-notes"><p><strong>Dining</strong><br/>{day.dining}</p><p><strong>Travel and rest</strong><br/>{day.transitAndRest}</p><p><strong>Dietary arrangements · confirm with venues</strong><br/>{day.dietaryNotes}</p><p><strong>Access · confirm with venues</strong><br/>{day.mobilityNotes}</p></div>
      <details className="secondary-tools"><summary>Day outline</summary><p><strong>Morning</strong><br/>{day.morning}</p><p><strong>Afternoon</strong><br/>{day.afternoon}</p><p><strong>Evening</strong><br/>{day.evening}</p></details>
      <details className="secondary-tools"><summary>Day expense breakdown</summary><p className="hint">Estimates for the whole group, not per person.</p><ul className="budget-list">{Object.entries(COST_LABELS).map(([key,label])=><li key={key}><span>{label}</span><span>{money(currency,Math.round(day.costs[key]*100))}</span></li>)}</ul></details>
      {index===0&&<details className="secondary-tools"><summary>Route &amp; notes · {section.startDate} to {section.endDate}</summary>
      <p>{section.checkpoint.startLocation} → {section.checkpoint.endLocation}</p>
      <p className="hint">Estimate for these dates: {money(currency,section.checkpoint.spentCents)} for the whole group.</p>
      <p>{itinerary.explanation}</p>
      {!!itinerary.warnings.length&&<><h3>Things to check</h3><ul>{itinerary.warnings.map((warning,index)=><li key={index}>{warning}</li>)}</ul></>}
      <HistoricalSources section={section}/>
    </details>}
    </details>)}
  </section>;
}

export function SavedAdaptiveTripReader({tripID,client}) {
  const fallback=useRef(null);if(!fallback.current)fallback.current=createSavedAdaptiveClient();
  const api=client || fallback.current,scope=useRef(null);
  const [state,setState]=useState({page:null,busy:false,error:'',signedOut:false});
  const [deletion,setDeletion]=useState('idle');
  useDestinationTheme(state.page?.saved.destination || '');
  async function load() {
    const current=scope.current;
    if(!current||current.disposed||current.active||getSession()!==current.session)return;
    const controller=new AbortController();current.active=controller;current.confirmVersion=null;
    const valid=()=>scope.current===current&&!current.disposed&&!controller.signal.aborted&&getSession()===current.session;
    setState(previous=>({...previous,busy:true,error:''}));
    try {
      const firstPage=await api.get(tripID,{afterSequence:0,signal:controller.signal});
      if(!valid())return;
      const identity=page=>JSON.stringify([page.saved,page.preferences,page.journeyStrategy]);
      const page=await readContinuousDays({firstPage,identity,expectedDays:firstPage.saved.totalDays,startDate:firstPage.saved.startDate,signal:controller.signal,
        readPage:(cursor,{signal})=>api.get(tripID,{afterSequence:cursor,signal}),
        onPage:page=>{if(valid()){current.deleteUnknown=false;setDeletion('idle');setState(previous=>{
          const retained=previous.page;
          const sameLongerPrefix=retained&&identity(retained)===identity(page)&&retained.sections.length>page.sections.length&&page.sections.every((section,index)=>JSON.stringify(section)===JSON.stringify(retained.sections[index]));
          return {page:sameLongerPrefix?retained:page,busy:true,error:'',signedOut:false};
        });}},
      });
      if(valid()){current.deleteUnknown=false;setDeletion('idle');setState({page,busy:false,error:'',signedOut:false});}
    } catch(error) {
      if(valid())setState(previous=>({...previous,page:error?.code==='SAVED_ADAPTIVE_NOT_FOUND'?null:previous.page,busy:false,error:error?.code==='SAVED_ADAPTIVE_NOT_FOUND'?'This saved trip could not be found or is not available to your account.':continuousDaysMessage(error)}));
    } finally {if(current.active===controller)current.active=null;}
  }
  async function remove() {
    const current=scope.current;
    if(!current||current.disposed||current.active||current.deleteUnknown||getSession()!==current.session||deletion!=='confirm'||!state.page||current.confirmVersion!==state.page.saved.version)return;
    const controller=new AbortController();current.active=controller;
    const version=state.page.saved.version;current.confirmVersion=null;setDeletion('removing');setState(previous=>({...previous,busy:true,error:''}));
    try {
      const result=await api.remove(tripID,version,{signal:controller.signal});
      if(result?.id!==tripID||result?.deleted!==true||result?.version!==version)throw Error('Unconfirmed deletion');
      if(scope.current===current&&!current.disposed&&!controller.signal.aborted&&getSession()===current.session){setDeletion('deleted');setState(previous=>({...previous,page:null,busy:false,error:''}));}
    } catch {
      if(scope.current===current&&!current.disposed&&!controller.signal.aborted&&getSession()===current.session){current.deleteUnknown=true;setDeletion('unknown');setState(previous=>({...previous,busy:false,error:'The deletion outcome is not confirmed. Check this saved trip before trying another action.'}));}
    } finally {if(current.active===controller)current.active=null;}
  }
  useEffect(()=>{
    setDeletion('idle');
    const session=getSession();
    if(!session?.user?.id){setState({page:null,busy:false,error:'',signedOut:true});return;}
    const current={session,active:null,disposed:false};scope.current=current;
    setState({page:null,busy:false,error:'',signedOut:false});
    const unsubscribe=subscribeSession(next=>{if(next!==session){current.disposed=true;current.active?.abort();setDeletion('idle');setState({page:null,busy:false,error:'',signedOut:true});}});
    void load();
    return()=>{current.disposed=true;current.active?.abort();unsubscribe();if(scope.current===current)scope.current=null;};
  },[tripID,api]);
  const {page,busy,error,signedOut}=state,saved=page?.saved;
  return <main className="page"><SiteHeader showSavedTrips/>
    <Link to="/saved-trips">← Back to saved trips</Link>
    <section className="card adaptive-progress">
      <p className="eyebrow">Account-saved trip</p><h1>{saved?.title || 'Your saved trip'}</h1>
      {signedOut?<p role="status">Sign in again to open saved trips for your account.</p>:<>
        {busy&&<p role="status">{deletion==='removing'?'Deleting this saved account copy…':'Loading saved trip days…'}</p>}
        {deletion==='deleted'&&<p role="status">This saved account copy was deleted. The original temporary plan is unchanged.</p>}
        {error&&<><p role="alert">{error}</p><button className="preview-btn" disabled={busy} onClick={()=>load()}>Check this saved trip</button></>}
        {saved&&<>
          <p>{saved.destination} · <time dateTime={saved.startDate}>{saved.startDate}</time> to <time dateTime={saved.endDate}>{saved.endDate}</time> · {saved.totalDays} planned days</p>
          <p>Saved to your account on <time dateTime={saved.createdAt}>{new Date(saved.createdAt).toLocaleDateString()}</time>. This copy remains separate from the original temporary planning session and its expiry.</p>
          <p className="hint">Saved version. Estimates and historical research are not live prices, verified schedules or bookings.</p>
          <ul className="budget-list"><li><span>Saved whole-trip estimate</span><strong>{money(saved.currency,saved.spentCents)}</strong></li><li><span>Original group budget</span><span>{money(saved.currency,saved.totalBudgetCents)}</span></li><li><span>Budget not allocated in this saved estimate</span><span>{money(saved.currency,BigInt(saved.totalBudgetCents)-BigInt(saved.spentCents))}</span></li></ul>
          <p className="hint">Costs cover all {saved.totalDays} saved days for the whole group ({page.preferences.travelers} {page.preferences.travelers===1?'traveler':'travelers'}), not just the days on this page.</p>
          <SavedTripPdfButton tripID={tripID} disabled={busy||deletion!=='idle'}/>
          <div className="secondary-tools">
            {deletion==='confirm'?<section aria-label="Confirm saved copy deletion"><p>Delete this saved account copy? This cannot be undone. The original temporary plan remains unchanged.</p><button className="preview-btn" disabled={busy} onClick={remove}>Confirm delete saved copy</button><button className="preview-btn" disabled={busy} onClick={()=>{if(scope.current)scope.current.confirmVersion=null;setDeletion('idle');}}>Keep saved copy</button></section>:<button className="preview-btn" disabled={busy||deletion==='unknown'} onClick={()=>{const current=scope.current;if(!current||current.disposed||current.active||current.deleteUnknown||getSession()!==current.session)return;current.confirmVersion=saved.version;setDeletion('confirm');}}>Delete saved copy</button>}
          </div>
          <details className="secondary-tools"><summary>Saved trip route</summary><p>{page.journeyStrategy.summary}</p><ul>{page.journeyStrategy.stays.map(stay=><li key={`${stay.startDate}-${stay.endDate}`}><time dateTime={stay.startDate}>{stay.startDate}</time> to <time dateTime={stay.endDate}>{stay.endDate}</time> · {stay.location}</li>)}</ul></details>
        </>}
      </>}
    </section>
    {!signedOut&&page&&<div className="results-wrap">
      {page.sections.map(section=><SavedSection key={section.id} section={section} currency={saved.currency} tripStart={saved.startDate}/>)}
      <p className="hint">{visibleDayRange(page.sections,saved.startDate)}. {page.sections.reduce((count,section)=>count+section.checkpoint.itinerary.days.length,0)} of {saved.totalDays} saved days shown.{busy&&' Loading the remaining days…'} All days remain saved to your account.</p>
    </div>}
  </main>;
}
export default function SavedAdaptiveTripPage({client}) {
  const {tripID}=useParams();
  return <SavedAdaptiveTripReader key={tripID} tripID={tripID} client={client}/>;
}
