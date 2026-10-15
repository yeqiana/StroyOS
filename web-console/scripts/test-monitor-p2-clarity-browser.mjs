import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3133/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const journey=async function(){
 const wait=async(fn,label)=>{for(let i=0;i<360;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,75))}throw Error('timeout '+label)};
 try{
 const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
 const monitorNav=[...nav.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='生产监控');
 if(!monitorNav)throw Error('monitor navigation missing');
 if(innerWidth===1440){
  const originalRedisFetch=window.fetch.bind(window);
  window.fetch=async function(input,...args){
   const response=await originalRedisFetch(input,...args);
   const url=String(typeof input==='string'?input:input?.url||'');
   if(!url.includes('/api/v1/local-monitor/tasks')&&!url.includes('/api/v1/local-monitor/workers'))return response;
   const payload=await response.clone().json();
   if(!payload?.data)throw Error('Redis test API envelope missing');
   if(url.includes('/api/v1/local-monitor/tasks')){
    Object.assign(payload.data,{available:true,scan_complete:true,record_count:2,running_claims:1,queued_claims:1,unverified_count:0,live_execution_verified:false,episode_binding_verified:false,records:[{task_tag:'R26-fixture',recorded_status:'RUNNING',episode_ref:null,frame:null,worker:null,updated_at:null,freshness_verified:false}]});
   }else{
    Object.assign(payload.data,{available:true,scan_complete:true,record_count:3,fresh_heartbeats:1,stale_heartbeats:0,unverified_heartbeats:2,worker_execution_verified:false});
   }
   return new Response(JSON.stringify(payload),{status:response.status,headers:{'Content-Type':'application/json'}});
  };
 }
 monitorNav.click();
 const monitor=await wait(()=>document.querySelector('#storyos-production-monitor-view'),'monitor');
 await wait(()=>monitor.querySelector('[aria-label="当前生产执行证据"]'),'execution evidence');
 const e=monitor.querySelector('[aria-label="当前生产执行证据"]');
 const interval=monitor.querySelector('[aria-label="刷新间隔"]');
 if(!interval?.closest('.ant-select')?.textContent?.includes('15 秒'))throw Error('15 second refresh default not represented in options');
 if(!e.textContent.includes('尚未核验'))throw Error('missing cautious execution status');
 const redisSummary=await wait(()=>monitor.querySelector('[aria-label="Redis 观测摘要"]'),'Redis first-screen summary');
 if(innerWidth===1440){
  await wait(()=>redisSummary.textContent.includes('2 条（自报运行 1）')&&redisSummary.textContent.includes('3 条（时间/TTL 新鲜 1）'),'mock Redis counts');
  if(!e.textContent.includes('尚未核验'))throw Error('claimed RUNNING misrepresented as verified execution');
  const redisDetails=monitor.querySelector('details[aria-label="Redis 只读技术证据"]');
  if(!redisDetails||redisDetails.open)throw Error('Redis evidence must remain collapsed by default');
  redisDetails.open=true;
  await wait(()=>redisDetails.textContent.includes('R26-fixture'),'mock Redis Task record');
  if(!redisDetails.textContent.includes('采集于'))throw Error('Redis evidence collection time missing');
  redisDetails.open=false;
 }
 await wait(()=>monitor.querySelector('.storyos-authority-grid button[aria-label^="查看权威阶段"]'),'stage row');
 const stageAction=monitor.querySelector('.storyos-authority-grid button[aria-label^="查看权威阶段"]');
 const stageRect=stageAction.getBoundingClientRect();
 if(stageRect.right>innerWidth+5||stageRect.left<0)throw Error('stage detail not visible within viewport');
 stageAction.click();
 const drawer=await wait(()=>document.querySelector('.storyos-authority-inspector'),'drawer');
 await wait(()=>drawer.querySelector('[aria-label="本次生产判断"]'),'detail verdict');
 if(!drawer.querySelector('[aria-label="本次生产判断"]').textContent.includes('未核验'))throw Error('detail verdict misleading');
 const detail=await wait(()=>drawer.querySelector('details[aria-label="生产技术证据"]'),'technical evidence');
 if(detail.open)throw Error('technical details expanded by default');
 if(!drawer.textContent.includes('下一步'))throw Error('no next action guidance');
 if(innerWidth===1440){
  const originalFetch=window.fetch.bind(window);
  let injected=false;
  window.fetch=async function(input,...args){
   const response=await originalFetch(input,...args);
   const url=String(typeof input==='string'?input:input?.url||'');
   if(!url.includes('/api/v1/runtime/statuses?limit=100&offset=0'))return response;
   const payload=await response.clone().json();
   if(!payload?.data?.items?.length)return response;
   payload.data.items[0].production_stage='VISUAL_CALIBRATED';
   payload.data.items[0].updated_at='2026-10-15T22:12:00+08:00';
   injected=true;
   return new Response(JSON.stringify(payload),{status:response.status,headers:{'Content-Type':'application/json'}});
  };
  monitor.querySelector('button[aria-label="手动刷新阶段证据"]').click();
  await wait(()=>injected&&drawer.querySelector('dl')?.textContent.includes('视觉校准'),'open drawer follows refreshed stage');
  window.fetch=async function(input,...args){
   const url=String(typeof input==='string'?input:input?.url||'');
   if(url.includes('/api/v1/runtime/statuses?limit=100&offset=0'))throw Error('simulated readonly endpoint outage');
   return originalFetch(input,...args);
  };
  monitor.querySelector('button[aria-label="手动刷新阶段证据"]').click();
  await wait(()=>!document.querySelector('.storyos-authority-inspector'),'stale drawer closes on offline data');
  window.fetch=originalFetch;
 }
 drawer.querySelector('.ant-drawer-close')?.click();
 await wait(()=>!document.querySelector('.ant-drawer-open'),'drawer close');
 const switcher=monitor.querySelector('[aria-label="生产监控视图"]');
 const historyTab=[...switcher.querySelectorAll('label')].find(x=>x.textContent.includes('历史 Run'));
 if(!historyTab)throw Error('history tab missing'); historyTab.click();
 await wait(()=>monitor.querySelector('.storyos-monitor-grid button'),'history table');
 if(!monitor.textContent.includes('记录时运行'))throw Error('historical running claim not labeled');
 if(!monitor.querySelector('[aria-label="按历史状态筛选"]'))throw Error('history filter should not imply live status');
 if(!monitor.textContent.includes('整部作品完成'))throw Error('historical completion caveat missing');
 const historyButton=monitor.querySelector('.storyos-monitor-grid button');
 const rect=historyButton.getBoundingClientRect();
 if(rect.right>innerWidth+5||rect.left<0)throw Error('history detail not visible within viewport');
 if(document.documentElement.scrollWidth>innerWidth+12)throw Error('horizontal page overflow');
 document.body.dataset.monitorP2='pass';
 }catch(e){document.body.dataset.monitorP2='fail:'+String(e.message||e)}
};
const filename='qa-monitor-p2.html';
try{
 for(const [label,width] of [['desktop',1440],['compact',1024],['mobile',390]]){
  fs.writeFileSync(filename,html.replace('</body>','<script>('+journey.toString()+')();</script></body>'));
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'monitor-p2-'+label+'-'));
  try{
   const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-extensions','--disable-dev-shm-usage','--virtual-time-budget=42000','--window-size='+width+',900','--user-data-dir='+profile,'--dump-dom',new URL('/'+filename,base).href],{encoding:'utf8',timeout:110000,maxBuffer:8000000});
   const result=r.stdout?.match(/data-monitor-p2="([^"]+)"/)?.[1]||'missing';
   assert.equal(result,'pass',label+': '+result+' '+String(r.stderr||'').slice(-160));
   console.log('PASS monitor P2',label);
  }finally{try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
 }
}finally{try{fs.rmSync(filename,{force:true})}catch{}}
console.log('MONITOR_P2_CHROME_3_OF_3_PASS');
