// Callback credentials are consumed once, removed from the address bar immediately,
// verified by the existing auth server, and never installed as an app session.
export function consumeConfirmationCallback({location,history,fetchImpl=globalThis.fetch,timeoutMs=10000}={}) {
  if(!location || !history)return null;
  const fragment=new URLSearchParams((location.hash||'').slice(1));
  const query=new URLSearchParams(location.search||'');
  const keys=['access_token','refresh_token','token_type','type','error','error_code','error_description','code'];
  if(!keys.some(key=>fragment.has(key)||query.has(key)))return null;
  // Do this before any asynchronous work. Never copy credentials into history state.
  try { history.replaceState(null,'',location.pathname||'/'); }
  catch { return Promise.resolve('unverified'); }
  const unique=key=>fragment.getAll(key).length===1;
  let token=fragment.get('access_token');
  if(query.size || fragment.has('error') || fragment.has('error_code') ||
      !unique('access_token') || !unique('type') || !unique('token_type') ||
      fragment.get('type')!=='signup' || fragment.get('token_type')!=='bearer' ||
      typeof token!=='string' || !/^[A-Za-z0-9._~-]{1,16384}$/.test(token)) {
    token=null;return Promise.resolve('unverified');
  }
  return (async()=>{
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),timeoutMs);
    try {
      const response=await fetchImpl('/api/auth/confirmation',{method:'GET',headers:{Authorization:`Bearer ${token}`},signal:controller.signal,cache:'no-store',redirect:'error',credentials:'omit'});
      if(response.status===401||response.status===403)return 'unverified';
      if(response.status!==200)return 'unavailable';
      const value=await response.json();return value?.confirmed===true?'verified':'unverified';
    } catch {return 'unavailable';}
    finally {token=null;clearTimeout(timer);}
  })();
}
let consumed=false,pending=null;
export function getConfirmationCallback() {
  if(!consumed && typeof window!=='undefined') {
    consumed=true;pending=consumeConfirmationCallback({location:window.location,history:window.history});
  }
  return pending;
}
