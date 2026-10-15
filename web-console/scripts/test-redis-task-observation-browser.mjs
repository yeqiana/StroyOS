import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3127/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome));
const r=await fetch(new URL('/api/v1/local-monitor/tasks',base));
assert.equal(r.status,200);
const payload=(await r.json()).data;
assert.equal(payload.scope,'LOCAL_REDIS_TASK_STATE_OBSERVATION');
assert.equal(payload.read_only,true);
assert.equal(payload.live_execution_verified,false);
assert.equal(payload.episode_binding_verified,false);
assert.equal((await fetch(new URL('/api/v1/local-monitor/tasks?all=true',base))).status,403);
assert.equal((await fetch(new URL('/api/v1/local-monitor/tasks',base),{method:'POST',body:'{}'})).status,403);
assert.equal((await fetch(new URL('/api/v1/local-monitor/tasks',base),{headers:{Origin:'https://other.example'}})).status,403);
const html=fs.readFileSync('index.html','utf8');
const journey=async function() {
 const wait=async(fn,who)=>{for(let i=0;i<310;i++){const x=fn();if(x)return x;await new Promise(r=>setTimeout(r,90))}throw Error('missing '+who)};
 try{
 const nav=await wait(()=>[...document.querySelectorAll('nav[aria-label="主要页面"] button')].find(x=>x.textContent?.trim()==='生产监控'),'production monitor');
 nav.click();
 const task=await wait(()=>{const a=document.querySelector('[aria-label="Redis Task 状态只读观测"]');return a&&a.textContent?.includes('Task ID')?a:null},'task panel');
 const snapshot=(await (await fetch('/api/v1/local-monitor/tasks')).json()).data;
 if(!task.textContent.includes('不等于正在生产'))throw Error('false live status hazard');
 if(snapshot.available){
   await wait(()=>task.textContent.includes('已扫描 '+snapshot.record_count),'task count');
   if(snapshot.record_count===0 && snapshot.scan_complete && !task.textContent.includes('不能据此断言'))throw Error('missing empty-state limitation');
 }
 if(document.documentElement.scrollWidth>innerWidth+10)throw Error('overflow');
 document.body.dataset.taskMonitorResult='pass';
 }catch(e){document.body.dataset.taskMonitorResult='fail:'+(e.message||e)}
};
for(const [label,width] of [['desktop',1440],['compact',1024]]){
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-redis-task-monitor-'));
 const file='qa-redis-task-monitor-'+label+'.html';
 assert.ok(!fs.existsSync(file));
 fs.writeFileSync(file,html.replace('</body>','<script>('+journey+')();</script></body>'));
 try{
 const result=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=30000','--window-size='+width+',900','--user-data-dir='+profile,'--dump-dom',new URL('/'+file,base).href],{encoding:'utf8',timeout:99000,maxBuffer:8000000});
 const mark=result.stdout?.match(/data-task-monitor-result="([^"]+)"/)?.[1]||'MISSING';
 assert.equal(mark,'pass',label+': '+mark+' '+String(result.stderr||'').slice(-220));
 console.log('PASS Redis Task UI',label);
 }finally{try{fs.unlinkSync(file)}catch{}try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
}
console.log('REDIS_TASK_READ_ONLY_BROWSER_2_OF_2_PASS; snapshot count='+payload.record_count);
