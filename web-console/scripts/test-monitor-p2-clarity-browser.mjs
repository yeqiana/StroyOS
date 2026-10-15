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
 if(!monitorNav)throw Error('monitor navigation missing'); monitorNav.click();
 const monitor=await wait(()=>document.querySelector('#storyos-production-monitor-view'),'monitor');
 await wait(()=>monitor.querySelector('[aria-label="当前生产执行证据"]'),'execution evidence');
 const e=monitor.querySelector('[aria-label="当前生产执行证据"]');
 if(!e.textContent.includes('尚未核验'))throw Error('missing cautious execution status');
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
 drawer.querySelector('.ant-drawer-close')?.click();
 await wait(()=>!document.querySelector('.ant-drawer-open'),'drawer close');
 const switcher=monitor.querySelector('[aria-label="生产监控视图"]');
 const historyTab=[...switcher.querySelectorAll('label')].find(x=>x.textContent.includes('历史 Run'));
 if(!historyTab)throw Error('history tab missing'); historyTab.click();
 await wait(()=>monitor.querySelector('.storyos-monitor-grid button'),'history table');
 if(!monitor.textContent.includes('记录时运行'))throw Error('historical running claim not labeled');
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
