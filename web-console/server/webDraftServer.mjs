import {createServer} from 'node:http';
import {randomBytes,timingSafeEqual} from 'node:crypto';

const LIMIT=2_100_000;
const PREFIX='/api/v1/web-drafts';
const SESSION_ROUTE=PREFIX+'/session';
const SESSION_TTL_MS=15*60*1000;
const BASE_ORIGINS=['http://127.0.0.1:3100','http://localhost:3100'];
function send(res,status,code,data=null,message=''){
 const raw=JSON.stringify({code,data,message});
 res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(raw),
  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'});
 res.end(raw);
}
function equal(a,b){
 const left=Buffer.from(a||''),right=Buffer.from(b||'');
 return left.length===right.length&&timingSafeEqual(left,right);
}
const fail=(status,code,message=code)=>Object.assign(Error(message),{status,code});
async function readJson(req){
 let size=0;const parts=[];
 if(Number(req.headers['content-length']||'0')>LIMIT)throw fail(413,'BODY_TOO_LARGE');
 for await(const buf of req){size+=buf.length;if(size>LIMIT)throw fail(413,'BODY_TOO_LARGE');parts.push(buf);}
 try{const object=JSON.parse(Buffer.concat(parts).toString('utf8'));
  if(!object||Array.isArray(object)||typeof object!=='object')throw Error('object expected');
  return object;
 }catch{throw fail(400,'INVALID_JSON');}
}
export function createWebDraftServer(store,{token,port=19119,allowedBrowserOrigin,backend='mysql8_web_drafts',bootstrapToken}={}){
 if((process.env.STORYOS_WEB_DRAFTS_ENABLE!=='1'&&process.env.STORYOS_WEB_DRAFTS_TEST_ONLY!=='1')||typeof token!=='string'||token.length<32)
  throw Error('Explicit authorized draft-only mode and strong operator secret required');
 if(!Number.isSafeInteger(port)||port<1024||port>65535)throw Error('Invalid local port');
 if(allowedBrowserOrigin&&!/^http:\/\/(127\.0\.0\.1|localhost):[0-9]{4,5}$/.test(allowedBrowserOrigin))
  throw Error('Only loopback browser origins are permitted');
 const origins=new Set([...BASE_ORIGINS,...(allowedBrowserOrigin?[allowedBrowserOrigin]:[])]);
 const sessions=new Map();
 let bootstrapBusy=false;
 return createServer(async(req,res)=>{
  const host=req.headers.host,origin=req.headers.origin,site=req.headers['sec-fetch-site'];
  if(host!=='127.0.0.1:'+port&&host!=='localhost:'+port){send(res,403,'HOST_FORBIDDEN');return;}
  if(origin&&!origins.has(origin)){send(res,403,'ORIGIN_FORBIDDEN');return;}
  if(site&&!['same-origin','none'].includes(site)){send(res,403,'FETCH_SITE_FORBIDDEN');return;}
  const method=req.method||'GET',path=(req.url||'').split('?')[0];
  if((req.url||'').includes('?')||!path.startsWith(PREFIX)){
   send(res,404,'ROUTE_NOT_FOUND');return;
  }
  if(!['GET','POST','PUT','PATCH','DELETE'].includes(method)){send(res,405,'METHOD_FORBIDDEN');return;}
  try{
   const write=method!=='GET';
   if(write&&(!origin||req.headers['x-storyos-draft-intent']!=='confirmed')){
    throw fail(403,'WRITE_INTENT_REQUIRED');
   }
   if(path===SESSION_ROUTE&&method==='POST'){
    if(!equal(req.headers.authorization,'Bearer '+token))throw fail(401,'AUTH_REQUIRED');
    if(sessions.size>64){
     for(const [key,value] of sessions)if(value.expiresAt<Date.now())sessions.delete(key);
     if(sessions.size>64)throw fail(429,'SESSION_LIMIT');
    }
    const sessionToken=randomBytes(32).toString('base64url');
    const csrfToken=randomBytes(32).toString('base64url');
    const expiresAt=Date.now()+SESSION_TTL_MS;
    sessions.set(sessionToken,{csrfToken,origin,expiresAt,scope:'web_drafts:draft_only'});
    send(res,201,'OK',{session_token:sessionToken,csrf_token:csrfToken,
     expires_at:expiresAt,scope:'web_drafts:draft_only',backend,draft_only:true,canonical_episode_created:false});
    return;
   }
   const bearer=(req.headers.authorization||'').startsWith('Bearer ')
    ?req.headers.authorization.slice(7):'';
   const session=sessions.get(bearer);
   if(!session||session.expiresAt<Date.now()){
    if(session)sessions.delete(bearer);
    throw fail(401,'SESSION_REQUIRED');
   }
   if(origin&&origin!==session.origin)throw fail(403,'SESSION_ORIGIN_MISMATCH');
   if(write&&(!equal(req.headers['x-storyos-csrf'],session.csrfToken)||origin!==session.origin))
    throw fail(403,'CSRF_REQUIRED');
   if(path===SESSION_ROUTE&&method==='DELETE'){
    sessions.delete(bearer);send(res,200,'OK',{revoked:true});return;
   }
   const isBootstrap=path.endsWith('/bootstrap');
   if(isBootstrap){
    if(method!=='POST')throw fail(405,'METHOD_FORBIDDEN');
    if(process.env.STORYOS_WEB_DRAFTS_TEST_ONLY==='1'||process.env.STORYOS_WEB_BOOTSTRAP_ENABLE!=='1'
      ||typeof bootstrapToken!=='string'||bootstrapToken.length<32)throw fail(403,'EPISODE_BOOTSTRAP_DISABLED');
    if(!equal(req.headers['x-storyos-production-authorization'],bootstrapToken)
      ||req.headers['x-storyos-production-intent']!=='create-episode-only')throw fail(403,'EPISODE_CREATE_AUTH_REQUIRED');
   }
   if(method==='DELETE')throw fail(405,'METHOD_FORBIDDEN');
   if(bootstrapBusy&&(isBootstrap||method==='PUT'))throw fail(409,'EPISODE_BOOTSTRAP_BUSY');
   const body=write?await readJson(req):{};
   if(isBootstrap)bootstrapBusy=true;
   try{
    const [status,data]=await store.execute(method,path,body);
    send(res,status,'OK',data);
   }finally{if(isBootstrap)bootstrapBusy=false;}
  }catch(error){
   const status=Number.isInteger(error.status)&&error.status>=400&&error.status<600?error.status:500;
   send(res,status,error.code||'INTERNAL_ERROR',null,status>=500?'服务内部错误':error.message);
  }
 });
}
export function listenLocal(server,port=19119){
 return new Promise((resolve,reject)=>{
  server.once('error',reject);
  server.listen(port,'127.0.0.1',()=>{server.removeListener('error',reject);resolve(server);});
 });
}
