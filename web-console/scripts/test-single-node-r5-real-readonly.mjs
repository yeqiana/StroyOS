// Single-node REAL file evidence QA: loopback-only read-only API + Chrome.
// Does not create/update Episode files, touch MySQL/Redis, start Writer or issue Provider calls.
import assert from 'node:assert/strict';
import {spawn,spawnSync,execFileSync} from 'node:child_process';
import {createServer} from 'node:net';
import fs from 'node:fs';
import path from 'node:path';

const web=process.cwd(),root=path.resolve(web,'..');
const gitCommon=execFileSync('git',['rev-parse','--path-format=absolute','--git-common-dir'],{cwd:root,encoding:'utf8'}).trim();
const main=path.dirname(gitCommon);
assert.ok(fs.existsSync(path.join(main,'episodes')),'workspace Episode folder must exist');
const python=process.env.STORYOS_PYTHON||path.join(process.env.LOCALAPPDATA||'C:/Users/79873/AppData/Local','Programs','Python','Python312','python.exe');
const chrome=process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe';
assert.ok(fs.existsSync(python)&&fs.existsSync(chrome),'localhost Python and Chrome required');
assert.ok(fs.existsSync(path.join(web,'node_modules','vite','bin','vite.js')),'isolated frontend dependencies required');
async function freePort(){
  const server=createServer();
  await new Promise((resolve,reject)=>server.listen(0,'127.0.0.1',resolve).on('error',reject));
  const port=server.address().port;
  await new Promise(resolve=>server.close(resolve));
  return port;
}
const apiPort=await freePort(),webPort=await freePort();
assert.notEqual(apiPort,webPort);
const base='http://127.0.0.1:'+webPort;
const children=[];
function launch(bin,args,cwd,env=process.env){
  const proc=spawn(bin,args,{cwd,env,stdio:['ignore','pipe','pipe'],windowsHide:true});
  children.push(proc);
  // Keep service output bounded; do not leak user Episode titles.
  proc.stdout.on('data',()=>{});
  proc.stderr.on('data',()=>{});
  return proc;
}
async function poll(url,verify){
  for(let i=0;i<90;i++){
    try{
      const result=await fetch(url,{signal:AbortSignal.timeout(2500)});
      if(result.ok&&await verify(result))return;
    }catch{}
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  throw Error('read-only local service unavailable at '+new URL(url).pathname);
}
async function req(endpoint,options={}){
  const r=await fetch(base+endpoint,{...options,signal:AbortSignal.timeout(8500),cache:'no-store'});
  let json;try{json=await r.json()}catch{}
  return {status:r.status,json};
}
try{
  launch(python,[path.join(root,'scripts','storyos_local_readonly_api.py'),'--workspace-root',main,'--port',String(apiPort)],root);
  await poll('http://127.0.0.1:'+apiPort+'/healthz',async r=>(await r.json()).code==='OK');
  launch(process.execPath,[path.join(web,'node_modules','vite','bin','vite.js'),'--host','127.0.0.1','--port',String(webPort),'--strictPort'],web,{
    ...process.env,STORYOS_PLATFORM_PROXY_TARGET:'http://127.0.0.1:'+apiPort,
    VITE_PLATFORM_API_URL:'',VITE_STORYOS_LOCAL_EVIDENCE_MODE:'true',DISABLE_HMR:'true'
  });
  await poll(base+'/api/v1/runtime/statuses?limit=1&offset=0',async r=>{
    const result=await r.json();
    return result.code==='OK'&&result.data?.total>0&&
      result.data.items?.[0]?.state_source==='local_workspace_episode_state_file';
  });
  const listing=await req('/api/v1/runtime/statuses?limit=100&offset=0');
  assert.equal(listing.status,200);
  assert.ok(listing.json.data.total>0);
  const list=listing.json.data.items;
  assert.ok(list.every(row=>row.state_source==='local_workspace_episode_state_file'));
  assert.equal(new Set(list.map(row=>row.episode_ref)).size,list.length,'actual Episode IDs must not collide');
  const ep=list[0].episode_ref;
  const detail=await req('/api/v1/runtime/status?episode='+encodeURIComponent(ep));
  assert.equal(detail.status,200);
  assert.equal(detail.json.data?.execution_status,'UNKNOWN','file status must not claim live Worker');
  assert.equal(detail.json.data?.heartbeat?.health,'unknown');
  const mutation=await req('/api/v1/runtime/statuses',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  assert.equal(mutation.status,403,'local evidence rejects mutations');
  const event=await req('/api/v1/events');
  assert.equal(event.status,403,'unregistered APIs fail closed');
  console.log('REAL_SINGLE_NODE_HTTP_PASS records='+listing.json.data.total+' stage-source=real-files unknown-worker=true mutation403=true');
  const args=['scripts/test-local-real-browser.mjs'];
  const result=spawnSync(process.execPath,args,{cwd:web,encoding:'utf8',timeout:100000,
    env:{...process.env,STORYOS_LOCAL_CONSOLE_URL:base+'/'},maxBuffer:4500000});
  if(result.status!==0){
    throw Error('Real Chrome local read-only pages failed: '+(result.stderr||result.stdout||'').slice(-1300));
  }
  console.log('REAL_SINGLE_NODE_CHROME_PASS true-files-home-and-monitor');
  const screenshot=path.join(root,'.storyos-tmp','ui-qa','single-node-r5-real-readonly-1440.png');
  fs.mkdirSync(path.dirname(screenshot),{recursive:true});
  const shot=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    '--virtual-time-budget=16000','--window-size=1440,900',
    '--user-data-dir='+path.join(root,'.storyos-tmp','ui-qa','r5-real-profile'),
    '--screenshot='+screenshot,base+'/'],{encoding:'utf8',timeout:80000});
  assert.ok(shot.status===0&&fs.existsSync(screenshot)&&fs.statSync(screenshot).size>3000,
            'Real local Chrome screenshot failed: '+(shot.stderr||'').slice(-300));
  console.log('REAL_SINGLE_NODE_SCREENSHOT '+path.relative(root,screenshot)+' bytes='+fs.statSync(screenshot).size);
}finally{
  // Terminate only the two services started by this QA script.
  for(const child of children.reverse()){
    if(child.exitCode===null){
      if(process.platform==='win32'){
        spawnSync('taskkill',['/PID',String(child.pid),'/T','/F'],{encoding:'utf8',timeout:9000,windowsHide:true});
      }else child.kill('SIGTERM');
    }
  }
}
