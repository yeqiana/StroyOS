import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3125/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome));
const html=fs.readFileSync('index.html','utf8');
const journey=async function(view){
 const wait=async(fn,label)=>{for(let i=0;i<320;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,70))}throw Error('timeout '+label)};
 try{
  const footer=await wait(()=>document.querySelector('.storyos-sidebar-footer'),'footer');
  const account=footer.querySelector('button[aria-label="账号菜单"]');
  if(!account)throw Error('account entry missing');
  if(document.querySelector('button[aria-label="系统设置"]'))throw Error('duplicate standalone settings entry');
  const full=getComputedStyle(footer.closest('.storyos-sidebar')).width!=='64px';
  if(full){
   if(footer.getBoundingClientRect().height>72)throw Error('footer should be single row '+footer.getBoundingClientRect().height);
   if(footer.textContent.includes('外观'))throw Error('redundant visible appearance label');
   const dark=footer.querySelector('button[aria-label="深色主题"]'),light=footer.querySelector('button[aria-label="浅色主题"]');
   if(!dark||!light)throw Error('direct theme shortcuts missing');
   light.click();
   await wait(()=>document.documentElement.classList.contains('theme-light'),'light shortcut');
   dark.click();
   await wait(()=>document.documentElement.classList.contains('theme-dark'),'dark shortcut');
  } else {
   const box=account.getBoundingClientRect();
   if(box.width>50||box.height<38)throw Error('compact account hitbox '+box.width+'x'+box.height);
   if(getComputedStyle(footer.querySelector('.storyos-sidebar-theme')).display!=='none')throw Error('compact theme should move to settings');
  }
  account.click();
  const menu=await wait(()=>document.querySelector('[role="menu"][aria-label="账号操作"]'),'account menu');
  if(!menu.textContent.includes('个人资料')||!menu.textContent.includes('进入演示账号')||!menu.textContent.includes('系统设置'))throw Error('account actions lost');
  if(!full){
   const m=menu.getBoundingClientRect(),sidebar=footer.closest('.storyos-sidebar').getBoundingClientRect();
   if(m.left<sidebar.right-2||m.right>innerWidth+3)throw Error('compact popup mispositioned '+m.left+'/'+m.right);
  }
  document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
  await wait(()=>!document.querySelector('[role="menu"]'),'Escape closes account');
  account.click();
  const settingsAction=await wait(()=>document.querySelector('[role="menu"] button[aria-label="系统设置（账号菜单）"]'),'menu settings');
  settingsAction.click();
  await wait(()=>document.querySelector('#codex-appearance-settings-view'),'settings via account');
  if(document.documentElement.scrollWidth>innerWidth+8)throw Error('horizontal overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
  document.body.dataset.footerResult='pass';
 }catch(e){document.body.dataset.footerResult='fail:'+(e.message||e)}
};
for(const [view,width] of [['desktop',1440],['compact',1024],['narrow',390]]){
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-footer-'+view+'-'));
 const name='qa-sidebar-footer-'+view+'.html';
 fs.writeFileSync(name,html.replace('</body>','<script>('+journey+')('+JSON.stringify(view)+');</script></body>'));
 try{
  const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=39000','--window-size='+width+',900','--user-data-dir='+profile,'--dump-dom',new URL('/'+name,base).href],{encoding:'utf8',timeout:112000,maxBuffer:11000000});
  const mark=r.stdout?.match(/data-footer-result="([^"]+)"/)?.[1]||'missing';
  assert.equal(mark,'pass',view+': '+mark+' '+String(r.stderr||'').slice(-150));
  console.log('PASS footer',view,'size, theme/settings, popup and Esc');
 }finally{try{fs.unlinkSync(name)}catch{}try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
}
console.log('STORYOS_REA_SIDEBAR_FOOTER_3_OF_3_PASS');
