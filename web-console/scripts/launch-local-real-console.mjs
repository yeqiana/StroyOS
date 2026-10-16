import assert from 'node:assert/strict';
import {spawn, execFileSync} from 'node:child_process';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {resolveLocalPython} from './resolve-local-python.mjs';

const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,'../..');
const web=path.resolve(root,'web-console');
const gitDir=execFileSync('git',['rev-parse','--path-format=absolute','--git-common-dir'],{cwd:root,encoding:'utf8'}).trim();
const dataRoot=path.resolve(process.env.STORYOS_LOCAL_DATA_ROOT||path.dirname(gitDir));
if(!fs.existsSync(path.join(dataRoot,'episodes')))throw Error('真实工作区缺少 episodes 目录');
const apiPort=Number(process.env.STORYOS_LOCAL_EVIDENCE_PORT || 19117);
const webPort=Number(process.env.STORYOS_LOCAL_CONSOLE_PORT || 3100);
if(!Number.isInteger(apiPort)||!Number.isInteger(webPort)||apiPort<1024||webPort<1024||apiPort>65535||webPort>65535||apiPort===webPort)throw Error('Invalid local ports');
const python=resolveLocalPython();
const vite=path.resolve(web,'node_modules','vite','bin','vite.js');
// Read a per-user local monitor config *only* for the Python read-only API.
// Never pass monitor credentials to Vite or browser-side environment variables.
function localMySqlMonitorEnv(){
  if(process.platform!=='win32') return {};
  const home=process.env.LOCALAPPDATA;
  if(!home) return {};
  const source=path.resolve(home,'StoryOS','monitoring','mysql-monitor-ro.json');
  try{
    const stat=fs.lstatSync(source);
    if(!stat.isFile()||stat.isSymbolicLink()||stat.size>4096) return {};
    const config=JSON.parse(fs.readFileSync(source,'utf8'));
    const user=config.STORYOS_MONITOR_MYSQL_RO_USER;
    const password=config.STORYOS_MONITOR_MYSQL_RO_PASSWORD;
    if(config.STORYOS_LOCAL_MONITOR_MYSQL!=='1'||
       !/^[A-Za-z0-9_.:-]{1,64}$/.test(user||'')||
       typeof password!=='string'||password.length<32||
       config.STORYOS_MONITOR_MYSQL_RO_DB!=='STORY_OS_RUNTIME'||
       String(config.STORYOS_MONITOR_MYSQL_RO_PORT)!=='3307') return {};
    return {
      STORYOS_LOCAL_MONITOR_MYSQL:'1',
      STORYOS_MONITOR_MYSQL_RO_USER:user,
      STORYOS_MONITOR_MYSQL_RO_PASSWORD:password,
      STORYOS_MONITOR_MYSQL_RO_DB:'STORY_OS_RUNTIME',
      STORYOS_MONITOR_MYSQL_RO_PORT:'3307',
    };
  }catch{
    // Missing, unreadable or malformed secrets keep monitoring disabled.
    return {};
  }
}

const children=[];
let closing=false;
function shutdown(code=0){
 if(closing)return;
 closing=true;
 for(const child of children)try{child.kill();}catch{}
 process.exitCode=code;
}
for(const sig of ['SIGINT','SIGTERM'])process.on(sig,()=>{shutdown();setTimeout(()=>process.exit(),800).unref();});
process.on('exit',()=>{for(const child of children)try{child.kill();}catch{}});
function start(file,args,cwd,env=process.env){
 const child=spawn(file,args,{cwd,env,stdio:['ignore','pipe','pipe'],windowsHide:true});
 children.push(child);
 child.stdout.on('data',data=>process.stdout.write('[local] '+data.toString()));
 child.stderr.on('data',data=>process.stderr.write('[local] '+data.toString()));
 child.once('error',error=>{console.error('Local child could not start:',error.message);shutdown(1);});
 child.once('exit',code=>{if(!closing){console.error('Local service stopped unexpectedly:',code);shutdown(1);}});
 return child;
}
// Cold startup and the first full episode-state scan can take longer when Chrome
// QA or another isolated worktree is busy. Never report READY from a partial probe.
async function poll(url,check){
 const deadline=Date.now()+60000;
 let lastResult='no response';
 while(Date.now()<deadline && !closing){
   try {
     const resp=await fetch(url,{signal:AbortSignal.timeout(5000),cache:'no-store'});
     if(resp.ok&&await check(resp))return;
     lastResult='HTTP '+resp.status+' or unexpected read-only evidence';
   }catch(error){
     lastResult=error?.name==='TimeoutError'?'request timed out':'connection unavailable';
   }
   await new Promise(resolve=>setTimeout(resolve,350));
 }
 throw Error('Local endpoint not ready ('+lastResult+'): '+url);
}
async function main(){
 console.log('本机真实状态文件只读：仅 127.0.0.1，读取用户主工作区 episodes；不启动生产 Runtime 或数据库');
 start(python,[path.resolve(root,'scripts','storyos_local_readonly_api.py'),'--workspace-root',dataRoot,'--port',String(apiPort)],root,{...process.env,STORYOS_LOCAL_MONITOR_REDIS:'1',...localMySqlMonitorEnv()});
 await poll('http://127.0.0.1:'+apiPort+'/healthz',async r=>(await r.json()).code==='OK');
 const viteEnv={...process.env,STORYOS_PLATFORM_PROXY_TARGET:'http://127.0.0.1:'+apiPort,VITE_PLATFORM_API_URL:'',VITE_STORYOS_LOCAL_EVIDENCE_MODE:'true'};
 start(process.execPath,[vite,'--host','127.0.0.1','--port',String(webPort),'--strictPort'],web,viteEnv);
 await poll('http://127.0.0.1:'+webPort+'/',async r=>(await r.text()).includes('id="root"'));
 await poll('http://127.0.0.1:'+webPort+'/api/v1/runtime/statuses?limit=1&offset=0',async r=>{
  const payload=await r.json();return payload.code==='OK'&&payload.data?.items?.[0]?.state_source==='local_workspace_episode_state_file'&&payload.data?.total>0;
 });
 console.log('LOCAL_STORYOS_READY http://127.0.0.1:'+webPort+'/');
 console.log('LOCAL_REAL_FILES_API http://127.0.0.1:'+apiPort+'/healthz');
 console.log('本机文件证据 + Redis 心跳与 Task 状态只读观测，均非 Writer/Attempt 执行授权；Ctrl+C 关闭本地服务。');
}
main().catch(error=>{console.error(error.message);shutdown(1);});