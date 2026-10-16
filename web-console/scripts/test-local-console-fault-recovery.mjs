import assert from 'node:assert/strict';
import net from 'node:net';
import {spawn,spawnSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
if(process.platform!=='win32'){console.log('SKIP Windows-only real local console fault test');process.exit(0)}
const sleep=t=>new Promise(resolve=>setTimeout(resolve,t));
async function freePort(){
 const s=net.createServer();
 await new Promise((resolve,reject)=>{s.once('error',reject);s.listen(0,'127.0.0.1',resolve)});
 const p=s.address().port;
 await new Promise(resolve=>s.close(resolve));return p;
}
const apiPort=await freePort(),webPort=await freePort();
assert.notEqual(apiPort,webPort);
async function probe(){
 try{
 const base='http://127.0.0.1:';
 const [a,w,e]=await Promise.all([
  fetch(base+apiPort+'/healthz',{signal:AbortSignal.timeout(2100)}),
  fetch(base+webPort+'/',{signal:AbortSignal.timeout(2100)}),
  fetch(base+webPort+'/api/v1/runtime/statuses?limit=1&offset=0',{signal:AbortSignal.timeout(3500)})
 ]);
 const [aj,html,ej]=await Promise.all([a.json(),w.text(),e.json()]);
 return a.ok&&aj.code==='OK'&&w.ok&&html.includes('id="root"')&&e.ok&&ej.code==='OK'&&ej.data?.total>0;
 }catch{return false}
}
function listenerPid(port){
 const result=spawnSync('netstat.exe',['-ano','-p','TCP'],{encoding:'utf8',timeout:8000,maxBuffer:3000000});
 if(result.status!==0)throw Error('netstat failed: '+result.stderr.slice(0,150));
 const lines=result.stdout.split(/\r?\n/);
 const owners=lines.filter(row=>row.includes('LISTENING')&&row.trim().split(/\s+/)[1]==='127.0.0.1:'+port);
 assert.equal(owners.length,1,'one owned localhost listener expected '+port);
 const pid=Number(owners[0].trim().split(/\s+/).at(-1));
 assert.ok(Number.isInteger(pid)&&pid>0);
 return pid;
}
function killPid(pid){
 // Windows taskkill.exe can block in the Runner service account; direct OS termination works.
 if(!Number.isInteger(pid)||pid<=0)throw Error('invalid test-owned PID');
 process.kill(pid,'SIGTERM');
}
let sup,output='',errors='';
const env={...process.env,STORYOS_LOCAL_EVIDENCE_PORT:String(apiPort),STORYOS_LOCAL_CONSOLE_PORT:String(webPort)};
try{
 assert.equal(await probe(),false,'test ports must be free before start');
 sup=spawn(process.execPath,[path.join(here,'supervise-local-console.mjs')],{cwd:path.resolve(here,'..'),env,stdio:['ignore','pipe','pipe'],windowsHide:true});
 sup.stdout.on('data',chunk=>{output+=String(chunk).slice(-2000);output=output.slice(-10000)});
 sup.stderr.on('data',chunk=>{errors+=String(chunk).slice(-2000);errors=errors.slice(-10000)});
 const wait=async(label,limit,condition)=>{
  const deadline=Date.now()+limit;
  while(Date.now()<deadline){
   if(sup.exitCode!==null)throw Error('supervisor exited '+sup.exitCode+' '+errors.slice(-1300));
   if(await condition())return;
   await sleep(1700);
  }
  throw Error('timeout '+label+' stdout='+output.slice(-1900)+' stderr='+errors.slice(-1000));
 };
 await wait('cold startup',110000,probe);
 console.log('PASS isolated console initial HTTP 200, ports '+apiPort+'/'+webPort);
 const apiPid=listenerPid(apiPort);
 // Only fault-inject the API process bound to ports reserved by this test.
 killPid(apiPid);
 await wait('API failure restart',120000,async()=>(output+errors).includes('准备重启')&&await probe());
 console.log('PASS killed isolated API recovered all three HTTP probes');
 const restarts=((output+errors).match(/准备重启/g)||[]).length;
 const vitePid=listenerPid(webPort);
 killPid(vitePid);
 await wait('Vite failure restart',120000,async()=>(((output+errors).match(/准备重启/g)||[]).length>restarts)&&await probe());
 console.log('PASS killed isolated Vite recovered all three HTTP probes');
 console.log('REAL_HTTP_SUPERVISOR_RECOVERY_2_OF_2_PASS');
}finally{
 if(sup&&sup.pid&&sup.exitCode===null&&sup.signalCode===null){
  // Gracefully stop only the supervisor process spawned by this test.
  sup.kill('SIGTERM');
  const ended=await Promise.race([new Promise(resolve=>sup.once('exit',()=>resolve(true))),sleep(15000).then(()=>false)]);
  if(!ended){console.error('TEST_CLEANUP_WARNING supervisor still alive');try{process.kill(sup.pid,'SIGTERM')}catch{}}
 }
}