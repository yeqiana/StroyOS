import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3129/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const journey=async function(){
 const wait=async(fn,label)=>{for(let i=0;i<260;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,100))}throw Error('timeout: '+label)};
 try{
  const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'main nav');
  const action=label=>[...nav.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')===label);
  for(const label of ['工作台','作品与项目','故事制作','生产监控']){
   if(!action(label))throw Error('missing primary '+label);
  }
  const advanced=action('高级管理');
  if(!advanced||advanced.getAttribute('aria-expanded')!=='false')throw Error('advanced not folded initially');
  if(action('工作流'))throw Error('advanced item shown initially');
  advanced.click();
  await wait(()=>action('工作流'),'workflow entry');
  for(const label of ['工作流','Agents','审计日志'])if(!action(label))throw Error('advanced entry missing '+label);
  action('Agents').click();
  await wait(()=>action('Agents').getAttribute('aria-current')==='page','agent route');
  action('生产监控').click();
  const monitor=await wait(()=>document.querySelector('#storyos-production-monitor-view'),'monitor');
  const evidence=await wait(()=>monitor.querySelector('details[aria-label="Redis 只读技术证据"]'),'redis details');
  if(evidence.open)throw Error('redis detail expanded by default');
  evidence.open=true;
  if(!evidence.querySelector('[aria-label="Redis Worker 心跳只读观测"]')||!evidence.querySelector('[aria-label="Redis Task 状态只读观测"]'))throw Error('redis evidence missing');
  if(!evidence.textContent.includes('自报 RUNNING 不等于正在生产'))throw Error('redis execution caveat lost');
  const account=await wait(()=>document.querySelector('.storyos-sidebar-footer button[aria-label="账号菜单"]'),'account');
  account.click();
  const settings=await wait(()=>document.querySelector('[role="menu"] button[aria-label="系统设置（账号菜单）"]'),'account settings');
  settings.click();
  const settingsView=await wait(()=>document.querySelector('#codex-appearance-settings-view'),'settings view');
  const tabs=settingsView.querySelectorAll('[role="tab"]');
  if(tabs.length!==5)throw Error('five settings tabs missing: '+tabs.length);
  if(!settingsView.querySelector('[aria-label="界面主题"]')||!settingsView.querySelector('[aria-label="字体偏好"]'))throw Error('appearance controls missing');
  if(document.documentElement.scrollWidth>innerWidth+12)throw Error('horizontal overflow');
  document.body.dataset.reaP1Result='pass';
 }catch(e){document.body.dataset.reaP1Result='fail:'+String(e.message||e)}
};
const file='qa-rea-p1-simplify.html';
fs.writeFileSync(file,html.replace('</body>','<script>('+journey+')();</script></body>'));
try{
 for(const [name,width] of [['desktop',1440],['compact',1024]]){
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-p1-'+name+'-'));
  try{
   const r=spawnSync(chrome,['--headless=new','--disable-gpu','--no-sandbox','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=38000','--window-size='+width+',900','--user-data-dir='+profile,'--dump-dom',new URL('/'+file,base).href],{encoding:'utf8',timeout:90000,maxBuffer:7000000});
   const marker=r.stdout?.match(/data-rea-p1-result="([^"]+)"/)?.[1]||'missing';
   assert.equal(marker,'pass',name+': '+marker+' '+String(r.stderr||'').slice(-220));
   console.log('PASS P1 navigation/monitor/settings',name);
  }finally{fs.rmSync(profile,{recursive:true,force:true})}
 }
}finally{fs.rmSync(file,{force:true})}
console.log('STORYOS_REA_P1_SIMPLIFICATION_2_OF_2_PASS');