import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import net from 'node:net';
import path from 'node:path';
import {nextHealthMisses,restartWindow} from './local-console-supervisor-core.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const web=path.resolve(here,'..');
const childScript=path.join(here,'launch-local-real-console.mjs');
const apiPort=Number(process.env.STORYOS_LOCAL_EVIDENCE_PORT||19117);
const webPort=Number(process.env.STORYOS_LOCAL_CONSOLE_PORT||3100);
if(![apiPort,webPort].every(p=>Number.isInteger(p)&&p>=1024&&p<=65535)||apiPort===webPort)throw Error('Invalid supervised console ports');
const snooze=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const check=async(url,verify)=>{
 try{
  const res=await fetch(url,{signal:AbortSignal.timeout(5000),cache:'no-store'});
  return res.ok&&await verify(res);
 }catch{return false}
};
async function healthy(){
 const base='http://127.0.0.1:';
 if(!await check(base+apiPort+'/healthz',async res=>(await res.json()).code==='OK'))return false;
 if(!await check(base+webPort+'/',async res=>(await res.text()).includes('id="root"')))return false;
 return check(base+webPort+'/api/v1/runtime/statuses?limit=1&offset=0',async res=>{
  const data=await res.json();return data.code==='OK'&&data.data?.items?.[0]?.state_source==='local_workspace_episode_state_file'&&data.data.total>0;
 });
}
function isPortFree(port){
 return new Promise(resolve=>{
  const server=net.createServer();
  server.once('error',()=>resolve(false));
  server.listen(port,'127.0.0.1',()=>server.close(()=>resolve(true)));
 });
}
let stop=false,child=null,childDead=false,failures=0,bootAt=0,wasReady=false,restarts=[];
function halt(){
 if(stop)return;
 stop=true;
 try{child?.kill()}catch{}
}
for(const sig of ['SIGINT','SIGTERM'])process.on(sig,halt);
async function portCheck(){
 if(!await isPortFree(apiPort)||!await isPortFree(webPort))
  throw Error('端口 '+apiPort+'/'+webPort+' 已被其他进程占用；拒绝接管或强杀未知服务');
}
function start(){
 childDead=false;failures=0;wasReady=false;bootAt=Date.now();
 child=spawn(process.execPath,[childScript],{cwd:web,env:process.env,windowsHide:true,stdio:['ignore','inherit','inherit']});
 child.on('error',error=>{console.error('[supervisor] 启动器失败:',error.message);childDead=true});
 child.on('exit',code=>{if(!stop){console.error('[supervisor] 启动器退出:',code);childDead=true}});
 console.log('[supervisor] 启动本机只读工作台');
}
async function stopChild(){
 if(!child)return;
 const prior=child;
 if(prior.exitCode===null)try{prior.kill()}catch{}
 await Promise.race([new Promise(done=>prior.once('exit',done)),snooze(2200)]);
 child=null;
}
async function main(){
 await portCheck();start();
 while(!stop){
  await snooze(10000);
  if(stop)break;
  const ok=!childDead&&await healthy();
  failures=nextHealthMisses(failures,ok);
  if(ok){if(!wasReady)console.log('[supervisor] HTTP 健康证据恢复');wasReady=true;continue}
  const exhausted=wasReady?failures>=3:Date.now()-bootAt>90000;
  if(!childDead&&!exhausted)continue;
  const budget=restartWindow(restarts,Date.now());
  if(!budget.allowed)throw Error('10 分钟内重启超过 3 次，已停止自动重试，请检查启动日志');
  console.warn('[supervisor] HTTP 失联或启动器退出，准备重启；连续异常次数='+failures);
  await stopChild();await snooze(1500);
  await portCheck();
  restarts=[...budget.history,Date.now()];
  start();
 }
 await stopChild();
}
main().catch(async error=>{console.error('[supervisor]',error.message);stop=true;await stopChild();process.exitCode=1;});