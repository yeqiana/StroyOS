import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';

const root=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(root.hostname,'127.0.0.1','R36 must inspect the actual local read-only console');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r36');
fs.mkdirSync(dir,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const cases=[{name:'workflow',menu:'工作流',selector:'#storyos-workflow-workspace',heading:'生产流程'},{name:'monitor',menu:'生产监控',selector:'#storyos-production-monitor-view',heading:'生产监控'}];

async function browserCase(c){
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const wait=async(fn,label)=>{for(let n=0;n<310;n++){const found=fn();if(found)return found;await sleep(85)}throw Error('timeout '+label)};
 const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
 const controls=[...document.querySelectorAll('button')];
 const menu=c.menu==='系统设置'?controls.find(x=>x.textContent?.trim()==='系统设置'):[...nav.querySelectorAll('button')].find(x=>x.textContent?.trim()===c.menu);
 if(!menu)throw Error('missing navigation menu '+c.menu);
 menu.click();
 const view=await wait(()=>document.querySelector(c.selector),'page '+c.name);
 await wait(()=>view.querySelector('h1')?.textContent?.trim()===c.heading,'page heading '+c.heading);
 let evidence='normal';
 if(c.name==='workflow'){
   const first=await wait(()=>view.querySelector('button[aria-label^="查看阶段详情："]'),'workflow row action');
   const label=first.getAttribute('aria-label');
   const seen=[];
   const rawFetch=window.fetch;
   window.fetch=(...args)=>{
     const target=String(args[0]?.url||args[0]);
     const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();
     if(target.includes('/api/v1/'))seen.push({method,url:target});
     return rawFetch(...args);
   };
   first.click();
   const drawer=await wait(()=>document.querySelector('.storyos-workflow-inspector .ant-drawer-body'),'workflow inspector');
   const triage=await wait(()=>drawer.querySelector('[aria-label="生产恢复安全诊断"] [data-recovery-code="local-evidence"]'),'safe workflow triage');
   await wait(()=>drawer.textContent?.includes('执行状态')&&drawer.textContent?.includes('本机状态文件'),'real workflow detail');
   if(!drawer.textContent.includes('禁止据此执行重试'))throw Error('missing fail-closed triage');
   if(!drawer.textContent.includes('未授权执行'))throw Error('missing authorization notice');
   if(!seen.some(req=>req.method==='GET'&&req.url.includes('/api/v1/runtime/status?episode=')))throw Error('workflow detail did not fetch canonical read-only detail');
   if(seen.some(req=>req.method!=='GET'))throw Error('workflow clicked unexpected mutation');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('triage has unauthorized action control');
   if(!label.includes('：'))throw Error('identity not displayed on action');
   const w=drawer.closest('.ant-drawer-content-wrapper')?.getBoundingClientRect().width;
   if(w>Math.min(innerWidth,440)+3)throw Error('workflow drawer too wide');
   if(!triage.textContent?.includes('仅有历史阶段证据'))throw Error('local evidence falsely marked recoverable');
   const matrix=await wait(()=>drawer.querySelector('[aria-label="Task Attempt Worker 生产证据矩阵"] .ant-descriptions'),'Ant Design evidence matrix');

   const cover=await wait(()=>drawer.querySelector('[data-authority-verified-count="0"]'),'R36 five-domain authority coverage');
   if(!cover.textContent?.includes('已核验 0/5'))throw Error('R36 local authority coverage must be 0/5');
   if(!drawer.textContent.includes('R36 · TTL / fencing'))throw Error('R36 driver and worker contract missing');
   if(!matrix.textContent.includes('MySQL Task 归属 + Redis TTL'))throw Error('R36 worker per-episode TTL requirement missing');
   if(!matrix.textContent.includes('PID 心跳不能代替唯一租约'))throw Error('R36 Writer PID incorrectly sufficient');
   if(!matrix.textContent.includes('UNKNOWN 不允许重派'))throw Error('R36 Attempt unknown boundary missing');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('R36 has an unauthorized operation button');

   const names=[...matrix.querySelectorAll('.ant-descriptions-item-label')].map(el=>el.textContent?.trim());
   for(const label of ['Task','Attempt','Worker','Writer','图片名额']){
     if(!names.includes(label))throw Error('R36 missing evidence source '+label);
   }
   if(!matrix.textContent.includes('当前持锁数未接入'))throw Error('R36 invented free image permits');
   if(!matrix.textContent.includes('MySQL Generation Attempt'))throw Error('R36 omitted attempt provenance');
   if(!matrix.textContent.includes('身份与权威心跳未验证'))throw Error('R36 implied online Worker without proof');
   if(!matrix.textContent.includes('Driver Owner'))throw Error('R36 owner/fence evidence missing');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('unsafe recovery control was introduced');
   matrix.scrollIntoView({block:'center',behavior:'instant'});
   await sleep(220);


   const statusLine=await wait(()=>drawer.querySelector('[data-authority-scope="LOCAL_READ_ONLY_EVIDENCE"]'),'R36 identity bound authority GET presentation');
   if(!statusLine.textContent?.includes('在线权威数据未授权接入'))throw Error('R36 local evidence claimed to be online');
   const receipts=seen.filter(req=>req.url.includes('/api/v1/runtime/authority?episode='));
   if(!receipts.length||receipts.some(req=>req.method!=='GET'))throw Error('R36 authority must be GET-only');
   const requested=new Set(receipts.map(req=>new URL(req.url,location.href).searchParams.get('episode')));
   if(requested.size!==1||![...requested][0]?.startsWith('LOCAL_'))throw Error('R36 cross episode read detected');
   const live=await fetch('/api/v1/runtime/authority?episode='+encodeURIComponent([...requested][0])).then(r=>r.json());
   if(live.code!=='OK'||live.data?.episode_ref!==[...requested][0])throw Error('R36 authority response not bound to selected Episode');
   if(live.data.production_authorization!==false||live.data.can_start!==false||live.data.can_retry!==false)throw Error('R36 unexpected production authorization');
   const domains=['task','attempt','worker','writer','capacity'];
   if(domains.some(name=>live.data.evidence[name]?.status!=='UNAVAILABLE'||live.data.evidence[name]?.reason!=='LOCAL_STAGE_ONLY'))throw Error('R36 local files masquerade as authoritative');
   if(seen.some(req=>req.method!=='GET'))throw Error('R36 unexpected mutation');
   if(!matrix.textContent.includes('当前持锁数未接入'))throw Error('R36 invented live capacity');
   await sleep(160);

   evidence='read-only workflow GET detail + local evidence recovery blocked';
 }else if(c.name==='monitor'){
   const area=await wait(()=>view.querySelector('[aria-label="只读状态记录及数据来源"]'),'monitor stage evidence');
   const first=await wait(()=>area.querySelector('button[aria-label^="查看权威阶段："]'),'monitor detail');
   const seen=[];
   const rawFetch=window.fetch;
   window.fetch=(...args)=>{
     const target=String(args[0]?.url||args[0]);
     const method=String(args[1]?.method||args[0]?.method||'GET').toUpperCase();
     if(target.includes('/api/v1/'))seen.push({method,url:target});
     return rawFetch(...args);
   };
   first.click();
   const drawer=await wait(()=>document.querySelector('.storyos-authority-inspector .ant-drawer-body'),'monitor inspector');
   const triage=await wait(()=>drawer.querySelector('[aria-label="生产恢复安全诊断"] [data-recovery-code="local-evidence"]'),'monitor fail closed triage');
   await wait(()=>drawer.textContent?.includes('执行状态')&&drawer.textContent?.includes('本机状态文件'),'monitor API detail');
   if(!seen.some(req=>req.method==='GET'&&req.url.includes('/api/v1/runtime/status?episode=')))throw Error('monitor did not GET actual detail');
   if(seen.some(req=>req.method!=='GET'))throw Error('monitor unexpectedly mutated state');
   if(!triage.textContent?.includes('仅有历史阶段证据'))throw Error('monitor implied production recovery without authority');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('unsafe recovery button');
   const w=drawer.closest('.ant-drawer-content-wrapper')?.getBoundingClientRect().width;
   if(w>Math.min(innerWidth,440)+3)throw Error('monitor drawer width');
   const matrix=await wait(()=>drawer.querySelector('[aria-label="Task Attempt Worker 生产证据矩阵"] .ant-descriptions'),'Ant Design evidence matrix');

   const cover=await wait(()=>drawer.querySelector('[data-authority-verified-count="0"]'),'R36 five-domain authority coverage');
   if(!cover.textContent?.includes('已核验 0/5'))throw Error('R36 local authority coverage must be 0/5');
   if(!drawer.textContent.includes('R36 · TTL / fencing'))throw Error('R36 driver and worker contract missing');
   if(!matrix.textContent.includes('MySQL Task 归属 + Redis TTL'))throw Error('R36 worker per-episode TTL requirement missing');
   if(!matrix.textContent.includes('PID 心跳不能代替唯一租约'))throw Error('R36 Writer PID incorrectly sufficient');
   if(!matrix.textContent.includes('UNKNOWN 不允许重派'))throw Error('R36 Attempt unknown boundary missing');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('R36 has an unauthorized operation button');

   const names=[...matrix.querySelectorAll('.ant-descriptions-item-label')].map(el=>el.textContent?.trim());
   for(const label of ['Task','Attempt','Worker','Writer','图片名额']){
     if(!names.includes(label))throw Error('R36 missing evidence source '+label);
   }
   if(!matrix.textContent.includes('当前持锁数未接入'))throw Error('R36 invented free image permits');
   if(!matrix.textContent.includes('MySQL Generation Attempt'))throw Error('R36 omitted attempt provenance');
   if(!matrix.textContent.includes('身份与权威心跳未验证'))throw Error('R36 implied online Worker without proof');
   if(!matrix.textContent.includes('Driver Owner'))throw Error('R36 owner/fence evidence missing');
   if(drawer.querySelector('[aria-label="生产恢复安全诊断"] button'))throw Error('unsafe recovery control was introduced');
   matrix.scrollIntoView({block:'center',behavior:'instant'});
   await sleep(220);


   const statusLine=await wait(()=>drawer.querySelector('[data-authority-scope="LOCAL_READ_ONLY_EVIDENCE"]'),'R36 identity bound authority GET presentation');
   if(!statusLine.textContent?.includes('在线权威数据未授权接入'))throw Error('R36 local evidence claimed to be online');
   const receipts=seen.filter(req=>req.url.includes('/api/v1/runtime/authority?episode='));
   if(!receipts.length||receipts.some(req=>req.method!=='GET'))throw Error('R36 authority must be GET-only');
   const requested=new Set(receipts.map(req=>new URL(req.url,location.href).searchParams.get('episode')));
   if(requested.size!==1||![...requested][0]?.startsWith('LOCAL_'))throw Error('R36 cross episode read detected');
   const live=await fetch('/api/v1/runtime/authority?episode='+encodeURIComponent([...requested][0])).then(r=>r.json());
   if(live.code!=='OK'||live.data?.episode_ref!==[...requested][0])throw Error('R36 authority response not bound to selected Episode');
   if(live.data.production_authorization!==false||live.data.can_start!==false||live.data.can_retry!==false)throw Error('R36 unexpected production authorization');
   const domains=['task','attempt','worker','writer','capacity'];
   if(domains.some(name=>live.data.evidence[name]?.status!=='UNAVAILABLE'||live.data.evidence[name]?.reason!=='LOCAL_STAGE_ONLY'))throw Error('R36 local files masquerade as authoritative');
   if(seen.some(req=>req.method!=='GET'))throw Error('R36 unexpected mutation');
   if(!matrix.textContent.includes('当前持锁数未接入'))throw Error('R36 invented live capacity');
   await sleep(160);

   evidence='read-only monitor GET detail + recovery guards';
 }
 await sleep(360);
 if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal viewport overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
 const main=document.querySelector('main');
 const actual=view.getBoundingClientRect();
 if(actual.width<Math.min(360,(main?.clientWidth||innerWidth)*.75))throw Error('page is unexpectedly narrow');
 return {name:c.name,heading:c.heading,evidence,width:innerWidth,usedWidth:Math.round(actual.width)};
}

// Start a clean Chrome process for each width: page contexts on Windows can be replaced
// when a previous Chrome profile exits, even when a previous CDP test finished.
const widthArg=process.argv.find(arg=>arg.startsWith('--width='));
if(!widthArg){
 for(const width of [1440,1024]){
   const result=spawnSync(process.execPath,[process.argv[1],'--width='+width],{stdio:'inherit',timeout:240000});
   if(result.status!==0)process.exit(result.status||1);
 }
 console.log('R36_WORKER_WRITER_TTL_FENCE_4_OF_4_PASS');
 process.exit(0);
}
const requestedWidth=Number(widthArg.slice('--width='.length));
assert.ok([1024,1440].includes(requestedWidth),'supported viewport required');
for(const width of [requestedWidth]){
 const profile=path.join(dir,'chrome-profile-'+width+'-'+process.pid);
 const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--remote-debugging-port=0',
   '--window-size='+width+',900','--user-data-dir='+profile,root.href],{stdio:'ignore'});
 let ws;
 try{
   const portFile=path.join(profile,'DevToolsActivePort');
   let port=null;
   for(let i=0;i<180;i++){
     if(fs.existsSync(portFile)){
       try{const value=Number(fs.readFileSync(portFile,'utf8').split('\n')[0]);if(Number.isInteger(value)&&value>0){port=value;break}}catch(error){if(!['EBUSY','EACCES','ENOENT'].includes(error?.code))throw error}
     }
     await sleep(100);
   }
   assert.ok(port,'Chrome CDP port unavailable');
   let target;
   for(let i=0;i<180;i++){
     try{target=(await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json())).find(x=>x.type==='page'&&x.url.startsWith(root.href));if(target)break}catch{}
     await sleep(100);
   }
   assert.ok(target?.webSocketDebuggerUrl,'Chrome page unavailable');
   ws=new WebSocket(target.webSocketDebuggerUrl);
   await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true})});
   let sequence=0;const pending=new Map();
   ws.addEventListener('message',e=>{let value;try{value=JSON.parse(e.data)}catch{return}if(!value.id||!pending.has(value.id))return;const promise=pending.get(value.id);pending.delete(value.id);value.error?promise.reject(Error(value.error.message)):promise.resolve(value.result)});
   const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
   await send('Runtime.enable');await send('Page.enable');
   // On narrow Windows headless Chrome, navigation can replace the first renderer context
   // immediately after CDP attaches. Wait for a stable document and retry only that transient.
   await sleep(1000);
   for(const c of cases){
      let response;
      for(let attempt=0;attempt<8;attempt++){
        try{
          response=await send('Runtime.evaluate',{expression:'('+browserCase.toString()+')('+JSON.stringify(c)+')',awaitPromise:true,returnByValue:true});
          break;
        }catch(error){
          // Windows Chrome may attach before the first default renderer context
          // exists. Reattempt evaluation only; never skip a page assertion.
          if(attempt===7||!/Execution context was destroyed|Cannot find default execution context|Cannot find context with specified id/.test(String(error)))throw error;
          await sleep(700);
        }
      }
      if(!response)throw Error('Browser context never became available '+c.name+' '+width);
      if(response.exceptionDetails)throw Error('Browser '+c.name+' '+width+': '+(response.exceptionDetails.exception?.description||response.exceptionDetails.text));
      const result=response.result?.value;
      if(!result||result.name!==c.name)throw Error('Missing browser verification '+c.name+' at '+width);
      await sleep(550);
      const image=await send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
      const filename=path.join(dir,'storyos-r36-'+c.name+'-'+width+'.png');
      fs.writeFileSync(filename,Buffer.from(image.data,'base64'));
      assert.ok(fs.statSync(filename).size>9000,'Screenshot failed '+c.name+' '+width);
      console.log('PASS '+c.name+' '+width+'px · '+result.evidence+' · screenshot '+fs.statSync(filename).size+' bytes');
   }
 }finally{if(ws)ws.close();child.kill();}
}
console.log('R36_WORKER_WRITER_TTL_FENCE_4_OF_4_PASS');
