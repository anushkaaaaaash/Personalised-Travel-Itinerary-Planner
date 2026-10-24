export function checkFrontendEnvironment(values,{hosted=false}={}) {
  if(Object.keys(values).some(k=>k.startsWith('VITE_')&&/(KEY|TOKEN|SECRET|PASSWORD)/i.test(k)))throw new Error('Secret-like VITE variables are not permitted. Use backend-only settings.');
  const value=values.VITE_API_BASE_URL||'/api';
  if(!hosted&&value==='/api')return value;
  let url;try{url=new URL(value);}catch{throw new Error('Hosted frontend requires an explicit HTTPS backend /api URL.');}
  if(url.protocol!=='https:'||url.username||url.password||url.search||url.hash||url.pathname!=='/api'||url.port)throw new Error('Invalid hosted API base URL.');
  return value;
}
