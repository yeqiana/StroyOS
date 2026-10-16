import assert from 'node:assert/strict';
import http from 'node:http';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
let fail=false;
const web=http.createServer((req,res)=>{
 res.setHeader('Content-Type','application/json');
 if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end('<div id="root"></div>');return}
 if(fail){res.writeHead(503);res.end('unavailable');return}
 if(req.url?.startsWith('/api/v1/runtime/statuses'))res.end(JSON.stringify({code:'OK',data:{total:1,items:[{state_source:'local_workspace_episode_state_file'}]}}));
 else res.end(JSON.stringify({code:'OK',data:{record_count:0}}));
});
const api=http.createServer((_req,res)=>{
 res.setHeader('Content-Type','application/json');res.end(JSON.stringify({code:'OK'}));
});
const listen=s=>new Promise(resolve=>s.listen(0,'127.0.0.1',resolve));
const close=s=>new Promise(resolve=>s.close(resolve));
async function run(port1,port2){
 const child=spawn(process.execPath,[path.join(here,'check-local-console-health.mjs')],{
  cwd:path.resolve(here,'..'),env:{...process.env,STORYOS_LOCAL_EVIDENCE_PORT:String(port1),STORYOS_LOCAL_CONSOLE_PORT:String(port2)},
  stdio:['ignore','pipe','pipe'],windowsHide:true,
 });
 let out='',err='';
 child.stdout.on('data',data=>out+=data.toString());
 child.stderr.on('data',data=>err+=data.toString());
 const result=await Promise.race([
  new Promise(resolve=>child.once('exit',code=>resolve({code}))),
  new Promise(resolve=>setTimeout(()=>resolve({timeout:true}),9000)),
 ]);
 if(result.timeout){child.kill();throw Error('status command timeout '+err)}
 return {code:result.code,report:JSON.parse(out)};
}
try{
 await Promise.all([listen(web),listen(api)]);
 const ok=await run(api.address().port,web.address().port);
 assert.equal(ok.code,0);assert.equal(ok.report.healthy,true);
 assert.equal(ok.report.execution_verified,false);
 assert.ok(Object.values(ok.report.endpoints).every(x=>x.ok));
 fail=true;
 const error=await run(api.address().port,web.address().port);
 assert.notEqual(error.code,0);
 assert.equal(error.report.healthy,false);
 assert.equal(error.report.endpoints.episode_stages.ok,false);
 console.log('PASS health CLI: expected evidence, red status, nonzero exit and no execution claim');
}finally{if(web.listening)await close(web);if(api.listening)await close(api)}