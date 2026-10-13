import {createServer} from 'node:http';
import {timingSafeEqual} from 'node:crypto';

const LIMIT=2_100_000;
const allowedOrigins=new Set(['http://127.0.0.1:3100','http://localhost:3100']);
const envelope=(code,data=null,message='')=>({code,data,message});
function send(res,status,code,data=null,message=''){
 const body=JSON.stringify(envelope(code,data,message));
 res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(body),
  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'});
 res.end(body);
}
function safeEqual(a,b){
 const one=Buffer.from(a||''),two=Buffer.from(b||'');
 return one.length===two.length&&timingSafeEqual(one,two);
}
export function createDraftMutationServer(store,{token,port=19118,allowedBrowserOrigin}={}){
 if(process.env.STORYOS_R17_TEST_ONLY!=='1'||!token||token.length<32)throw new Error('TEST_ONLY and strong operator secret required');
 if(!Number.isSafeInteger(port)||port<1024||port>65535)throw new Error('Invalid local port');
 if(allowedBrowserOrigin&&!/^http:\/\/(127\.0\.0\.1|localhost):[0-9]{4,5}$/.test(allowedBrowserOrigin))throw new Error('Only loopback browser origins are permitted');
 const browserOrigins=new Set([...allowedOrigins,...(allowedBrowserOrigin?[allowedBrowserOrigin]:[])]);
 return createServer(async(req,res)=>{
  const host=req.headers.host, origin=req.headers.origin, site=req.headers['sec-fetch-site'];
  if(host!=='127.0.0.1:'+port&&host!=='localhost:'+port){send(res,403,'HOST_FORBIDDEN');return;}
  if(origin&&!browserOrigins.has(origin)){send(res,403,'ORIGIN_FORBIDDEN');return;}
  if(site&&!['same-origin','none'].includes(site)){send(res,403,'FETCH_SITE_FORBIDDEN');return;}
  if(!safeEqual(req.headers.authorization,'Bearer '+token)){send(res,401,'AUTH_REQUIRED');return;}
  const method=req.method||'GET';
  if(!['GET','POST','PATCH'].includes(method)){send(res,405,'METHOD_FORBIDDEN');return;}
  if(method!=='GET'&&(!origin||req.headers['x-storyos-draft-intent']!=='confirmed')){
   send(res,403,'WRITE_INTENT_REQUIRED');return;
  }
  const path=(req.url||'').split('?')[0];
  if((req.url||'').includes('?')||!path.startsWith('/api/v1/draft-vault')){
   send(res,404,'ROUTE_NOT_FOUND');return;
  }
  let body={};
  if(method!=='GET'){
   try{
    if(Number(req.headers['content-length']||'0')>LIMIT){send(res,413,'BODY_TOO_LARGE');return;}
    let bytes=0,parts=[];
    for await(const chunk of req){
     bytes+=chunk.length;
     if(bytes>LIMIT){send(res,413,'BODY_TOO_LARGE');return;}
     parts.push(chunk);
    }
    const raw=Buffer.concat(parts).toString('utf8');
    body=JSON.parse(raw);
    if(!body||typeof body!=='object'||Array.isArray(body))throw Error('not object');
   }catch{send(res,400,'INVALID_JSON');return;}
  }
  try{
   const [status,data]=store.execute(method,path,body);
   send(res,status,'OK',data);
  }catch(e){
   const status=Number.isInteger(e.status)&&e.status>=400&&e.status<500?e.status:500;
   // Do not disclose driver, database paths or stack traces to browsers.
   send(res,status,e.code||'INTERNAL_ERROR',null,status===500?'服务内部错误':e.message);
  }
 });
}
export function listenLocal(server,port=19118){
 return new Promise((resolve,reject)=>{
  server.once('error',reject);
  server.listen(port,'127.0.0.1',()=>{server.removeListener('error',reject);resolve(server);});
 });
}
