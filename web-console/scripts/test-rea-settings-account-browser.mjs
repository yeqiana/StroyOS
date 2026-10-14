import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3121/');assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome),'Chrome required for UI tests');
const html=fs.readFileSync('index.html','utf8');
const journey=async function(view){
 const delay=ms=>new Promise(r=>setTimeout(r,ms));
 const wait=async(fn,label)=>{for(let i=0;i<300;i++){const v=fn();if(v)return v;await delay(80)}throw Error('timeout '+label)};
 try{
  const settings=await wait(()=>document.querySelector('button[aria-label="系统设置"]'),'settings button');
  settings.click();
  const page=await wait(()=>document.querySelector('#codex-appearance-settings-view'),'settings page');
  const tabs=await wait(()=>page.querySelector('.storyos-settings-tabs'),'setting tabs');
  const findTab=name=>[...tabs.querySelectorAll('.ant-tabs-tab')].find(t=>t.textContent?.includes(name));
  for(const n of ['外观设置','个人资料','通知与提醒','账号与安全','生产管线'])if(!findTab(n))throw Error('missing tab '+n);
  if(!page.querySelector('[aria-label="字体偏好"]'))throw Error('legacy font preference missing');
  findTab('个人资料').click();
  const profile=await wait(()=>page.querySelector('[aria-label="用户资料工作区"]'),'profile');
  for(const v of ['头像','显示名称','账号标识','邮箱','账号来源'])if(!profile.textContent.includes(v))throw Error('missing field '+v);
  if(!profile.textContent.includes('没有向本页提供账号认证')&&!profile.textContent.includes('未接入经过验证的账号身份'))throw Error('missing auth warning');
  if(profile.querySelector('input,textarea,form'))throw Error('fake editable profile');
  if(profile.textContent.includes('已登录')||profile.textContent.includes('会员等级'))throw Error('fictional identity');
  findTab('通知与提醒').click();
  await wait(()=>page.querySelector('[aria-label="通知设置工作区"]'),'notifications tab');
  if(!page.textContent.includes('尚无持久化接口'))throw Error('notification authority unclear');
  const open=page.querySelector('button[aria-label="打开通知中心"]');
  if(!open||open.disabled)throw Error('actual notifications button unavailable');
  open.click();
  await wait(()=>[...document.querySelectorAll('span')].some(e=>e.textContent?.trim()==='生产通知与质检流水'),'notification drawer');
  await wait(()=>document.body.textContent?.includes('本次会话暂无通知记录'),'empty notification state');
  document.querySelector('button[aria-label="关闭通知中心"]')?.click();
  await wait(()=>![...document.querySelectorAll('span')].some(e=>e.textContent?.trim()==='生产通知与质检流水'),'drawer close');
  findTab('账号与安全').click();
  const secure=await wait(()=>page.querySelector('[aria-label="账号安全工作区"]'),'security section');
  if(!secure.textContent.includes('未验证')||!secure.textContent.includes('未接入'))throw Error('security evidence boundary');
  if(secure.querySelector('input,textarea,form'))throw Error('fake security form');
  findTab('生产管线').click();
  const pipeline=await wait(()=>page.querySelector('[aria-label="生产配置双栏工作区"]'),'pipeline tab');
  if(!pipeline.textContent.includes('尚无已授权的生产配置读写接口'))throw Error('pipeline bypass');
  if(pipeline.querySelector('input,textarea,form'))throw Error('fake pipeline form');
  const accountMenu=document.querySelector('button[aria-label="账号菜单"]');
  if(!accountMenu)throw Error('sidebar account entry missing');
  accountMenu.click();
  const profileEntry=await wait(()=>document.querySelector('[role="menu"] button[aria-label="个人资料"]'),'profile account menu entry');
  profileEntry.click();
  await wait(()=>page.querySelector('[aria-label="用户资料工作区"]'),'sidebar profile navigation');
  if(!findTab('个人资料').classList.contains('ant-tabs-tab-active'))throw Error('profile sidebar not selected');
  const settingsBtn=document.querySelector('button[aria-label="系统设置"]');settingsBtn.click();
  await wait(()=>page.querySelector('[aria-label="字体偏好"]'),'settings default appearance');
  if(!findTab('外观设置').classList.contains('ant-tabs-tab-active'))throw Error('settings sidebar did not reset to appearance');
  if(document.documentElement.scrollWidth>innerWidth+8)throw Error('horizontal overflow');
  document.body.dataset.reaAccountStatus='pass';
 }catch(e){document.body.dataset.reaAccountStatus='fail:'+(e.message||e)}
};
for(const view of ['desktop','compact']){
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'rea-account-'+view+'-'));
 const filename='qa-rea-account-'+view+'.html';
 fs.writeFileSync(filename,html.replace('</body>','<script>('+journey+')('+JSON.stringify(view)+');</script></body>'));
 try{
  const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=42000','--window-size='+(view==='desktop'?'1440':'1024')+',900','--user-data-dir='+profile,'--dump-dom',new URL('/'+filename,base).href],{encoding:'utf8',timeout:112000,maxBuffer:9000000});
  const mark=r.stdout?.match(/data-rea-account-status="([^"]+)"/)?.[1]||'missing';
  assert.equal(mark,'pass',view+' real Chrome: '+mark+' stderr='+(r.stderr||'').slice(-200));
  console.log('PASS '+view+' settings five tabs, offline profile, notifications, security, navigation');
 }finally{try{fs.unlinkSync(filename)}catch{}try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
}
console.log('REA_SETTINGS_ACCOUNT_CHROME_2_OF_2_PASS');
