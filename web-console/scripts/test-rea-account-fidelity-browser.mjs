import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3124/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome),'Chrome executable is required');
const html=fs.readFileSync('index.html','utf8');
const journey=async function(layout){
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const wait=async(fn,label)=>{for(let i=0;i<400;i++){const v=fn();if(v)return v;await sleep(80)}throw Error('timeout '+label)};
 const press=(key,shiftKey=false)=>document.activeElement?.dispatchEvent(new KeyboardEvent('keydown',{key,shiftKey,bubbles:true,cancelable:true}));
 const menu=async()=>{document.querySelector('button[aria-label="账号菜单"]')?.click();return wait(()=>document.querySelector('[role="menu"][aria-label="账号操作"]'),'menu')};
 const clickMenu=async(label)=>{const m=await menu();const btn=m.querySelector('button[aria-label="'+label+'"]');if(!btn)throw Error('missing '+label);btn.click()};
 const fieldValue=(node,text)=>{const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;setter.call(node,text);node.dispatchEvent(new Event('input',{bubbles:true}));node.dispatchEvent(new Event('change',{bubbles:true}))};
 try{
  const button=await wait(()=>document.querySelector('button[aria-label="账号菜单"]'),'menu trigger');
  button.focus();
  press('ArrowDown');
  const options=await wait(()=>{const items=[...document.querySelectorAll('[role="menuitem"]')];return items.length===5?items:null},'menu keyboard open');
  if(options.length!==5)throw Error('wrong action count');
  await wait(()=>document.activeElement===options[0],'first action focus');
  press('ArrowDown');await wait(()=>document.activeElement===options[1],'arrow down');
  press('End');await wait(()=>document.activeElement===options[4],'end action');
  press('Home');await wait(()=>document.activeElement===options[0],'home action');
  press('ArrowUp');await wait(()=>document.activeElement===options[4],'arrow up wrap');
  press('Escape');await wait(()=>!document.querySelector('[role="menu"]')&&document.activeElement===button,'Escape returns focus');

  await clickMenu('进入演示账号');
  const dialog=await wait(()=>document.querySelector('[role="dialog"][aria-labelledby="mock-login-title"]'),'login dialog');
  const dimensions=dialog.getBoundingClientRect();
  if(layout==='desktop'&&dimensions.width<760)throw Error('desktop modal not two-column width '+dimensions.width);
  if(innerWidth<768&&dimensions.width>innerWidth+1)throw Error('mobile dialog exceeds viewport');
  if(!dialog.textContent.includes('不能获得生图')||!dialog.textContent.includes('Mock 认证'))throw Error('no mock boundary');
  if(dialog.querySelector('input'))throw Error('fake real-auth input');
  const first=dialog.querySelector('button[aria-label="关闭演示登录"]');
  const last=[...dialog.querySelectorAll('button')].at(-1);
  last.focus();press('Tab');await wait(()=>document.activeElement===first,'focus wraps from last to first');
  first.focus();press('Tab',true);await wait(()=>document.activeElement===last,'shift focus wraps');
  press('Escape');await wait(()=>!document.querySelector('[role="dialog"]')&&document.activeElement===button,'Escape dialog closes and focus restores');

  await clickMenu('进入演示账号');
  const login=await wait(()=>document.querySelector('button[aria-label="确认进入演示账号"]'),'login confirm');
  login.click();
  await wait(()=>button.textContent.includes('Mock 演示账号'),'logged in');
  await clickMenu('个人资料');
  const profile=await wait(()=>document.querySelector('[aria-label="用户资料工作区"]'),'profile');
  if(profile.querySelector('form'))throw Error('profile did not open in view mode');
  if(!profile.querySelector('[aria-label="演示资料概览"]'))throw Error('missing profile overview');

  profile.querySelector('button[aria-label="编辑演示资料"]').click();
  const input=await wait(()=>profile.querySelector('input[aria-label="演示昵称"]'),'edit mode');
  fieldValue(input,'这只是临时昵称');
  profile.querySelector('button[aria-label="取消编辑演示资料"]').click();
  await wait(()=>!profile.querySelector('input[aria-label="演示昵称"]'),'cancel edit');
  if(!profile.textContent.includes('演示用户'))throw Error('cancel failed to restore');
  profile.querySelector('button[aria-label="编辑演示资料"]').click();
  const next=await wait(()=>profile.querySelector('input[aria-label="演示昵称"]'),'reopen editor');
  fieldValue(next,'原创图文导演');
  profile.querySelector('button[aria-label="选择星光头像"]').click();
  profile.querySelector('button[type="submit"]').click();
  await wait(()=>profile.querySelector('[aria-label="演示资料概览"]')?.textContent.includes('原创图文导演'),'saved profile');
  if(!profile.textContent.includes('演示资料已保存到本机浏览器'))throw Error('save feedback lost');
  if(!button.textContent.includes('原创图文导演'))throw Error('account label not updated');
  await clickMenu('系统设置（账号菜单）');
  await wait(()=>document.querySelector('[aria-label="字体偏好"]'),'appearance settings');
  if(document.documentElement.scrollWidth>innerWidth+8)throw Error('horizontal document overflow');

  document.body.dataset.reaFidelityResult='pass';
 }catch(e){document.body.dataset.reaFidelityResult='fail:'+(e.message||e)}
};
for(const layout of ['desktop','compact','narrow']){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-account-fidelity-'));
 const filename='qa-rea-account-fidelity-'+layout+'.html';
 fs.writeFileSync(filename,html.replace('</body>','<script>('+journey+')('+JSON.stringify(layout)+');</script></body>'));
 try{
  const width=layout==='desktop'?1440:layout==='compact'?1024:390;
  const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=45000','--window-size='+width+',900','--user-data-dir='+dir,'--dump-dom',new URL('/'+filename,base).href],{encoding:'utf8',timeout:122000,maxBuffer:10000000});
  const mark=r.stdout?.match(/data-rea-fidelity-result="([^"]+)"/)?.[1]||'missing';
  assert.equal(mark,'pass',layout+': '+mark+' '+String(r.stderr||'').slice(-230));
  console.log('PASS account fidelity',layout,'keyboard/menu/dialog/profile/navigation');
 }finally{try{fs.unlinkSync(filename)}catch{}try{fs.rmSync(dir,{recursive:true,force:true})}catch{}}
}
console.log('REA_ACCOUNT_FIDELITY_CHROME_3_OF_3_PASS');
