import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';import os from 'node:os';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3122/');assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';assert.ok(fs.existsSync(chrome));
const html=fs.readFileSync('index.html','utf8');
const phases=['login-save','restore','expired','logged-out','storage-denied'];
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-mock-auth-'));
try{for(const phase of phases){
 const runProfile=phase==='storage-denied'?fs.mkdtempSync(path.join(os.tmpdir(),'storyos-mock-deny-')):profile;
 const name='qa-mock-auth-'+phase+'.html';
 fs.writeFileSync(name,html.replace('</body>','<script>('+(async function(phase){
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const wait=async(fn,label)=>{for(let i=0;i<350;i++){const x=fn();if(x)return x;await sleep(80)}throw Error('timeout '+label)};
 const menu=async()=>{const b=await wait(()=>document.querySelector('button[aria-label="账号菜单"]'),'account trigger');b.click();return await wait(()=>document.querySelector('[role="menu"][aria-label="账号操作"]'),'account popup')};
 const click=async(label)=>{const box=await menu();const b=box.querySelector('button[aria-label="'+label+'"]');if(!b)throw Error('no menu action '+label);b.click()};
 const modal=async()=>await wait(()=>document.querySelector('[role="dialog"][aria-labelledby="mock-login-title"]'),'login dialog');
 const enter=async()=>{await click('进入演示账号');const dialog=await modal();if(!dialog.textContent.includes('不能获得生图'))throw Error('missing mock boundary');dialog.querySelector('button[aria-label="确认进入演示账号"]').click();await wait(()=>!document.querySelector('[role="dialog"][aria-labelledby="mock-login-title"]'),'logged in');await wait(()=>document.querySelector('button[aria-label="账号菜单"]')?.textContent.includes('Mock 演示账号'),'logged mock');};
 const profile=async()=>{await click('个人资料');return await wait(()=>document.querySelector('[aria-label="用户资料工作区"]'),'profile page')};
 const type=(input,text)=>{const desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');desc.set.call(input,text);input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));};
 try{
  const trigger=await wait(()=>document.querySelector('button[aria-label="账号菜单"]'),'account trigger');
  if(phase==='login-save'){
   if(!trigger.textContent.includes('访客'))throw Error('expected guest');
   const box=await menu();
   if(!box.textContent.includes('不是生产授权'))throw Error('popup lacks mock scope');
   document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
   await wait(()=>!document.querySelector('[role="menu"]'),'Esc closes popup');
   await click('进入演示账号');
   let dialog=await modal();
   dialog.querySelector('button[aria-label="关闭演示登录"]').click();
   await wait(()=>!document.querySelector('[role="dialog"][aria-labelledby="mock-login-title"]'),'dialog close');
   await enter();
   const section=await profile();
   const field=section.querySelector('input[aria-label="演示昵称"]');
   if(!field)throw Error('mock profile editor not visible');
   type(field,'山地故事创作者');
   const photo=section.querySelector('button[aria-label="选择山峰头像"]');photo.click();
   await wait(()=>photo.getAttribute('aria-pressed')==='true','avatar state updated');
   section.querySelector('button[type="submit"]').click();
   await wait(()=>section.textContent.includes('演示资料已保存到本机浏览器'),'mock save');
   if(!localStorage.getItem('storyos:mock-ui-auth:v1')?.includes('山地故事创作者'))throw Error('not persisted');
   if(!trigger.textContent.includes('山地故事创作者'))throw Error('account menu did not update');
  }else if(phase==='restore'){
   await wait(()=>trigger.textContent.includes('山地故事创作者'),'saved nickname reload');
   const section=await profile();
   if(section.querySelector('input[aria-label="演示昵称"]')?.value!=='山地故事创作者')throw Error('profile not restored');
   await click('账号与安全（账号菜单）');
   const security=await wait(()=>document.querySelector('[aria-label="账号安全工作区"]'),'security tab');
   if(!security.textContent.includes('不能作为生产'))throw Error('missing separation of authority');
   const expire=security.querySelector('button[aria-label="模拟会话过期"]');
   if(!expire)throw Error('expire control missing');expire.click();
   await wait(()=>security.textContent.includes('Mock 会话已过期'),'expired UI');
   if(!localStorage.getItem('storyos:mock-ui-auth:v1')?.includes('expired'))throw Error('expired storage missing');
  }else if(phase==='expired'){
   if(!trigger.textContent.includes('Mock 会话已过期'))throw Error('expired state not restored');
   const section=await profile();
   if(section.querySelector('form'))throw Error('expired user still editable');
   const login=section.querySelector('button[aria-label="进入演示账号（个人资料）"]');login.click();
   (await modal()).querySelector('button[aria-label="确认进入演示账号"]').click();
   await wait(()=>trigger.textContent.includes('Mock 演示账号'),'re-enter');
   await click('退出演示账号');
   await wait(()=>trigger.textContent.includes('访客'),'signed out');
   if(localStorage.getItem('storyos:mock-ui-auth:v1'))throw Error('session not cleared');
  }else if(phase==='logged-out'){
   if(!trigger.textContent.includes('访客'))throw Error('logout not durable');
   await profile();
   if(document.querySelector('[aria-label="用户资料工作区"] input'))throw Error('guest editable profile');
   if(document.documentElement.scrollWidth>innerWidth+7)throw Error('narrow viewport overflows');
  }else if(phase==='storage-denied'){
   const proto=Storage.prototype, original=proto.setItem;
   proto.setItem=function(key,...args){if(key==='storyos:mock-ui-auth:v1')throw Error('storage denied');return original.call(this,key,...args)};
   await enter();
   const section=await profile();
   if(!section.textContent.includes('仅当前页面可用'))throw Error('denied persistence falsely claimed');
   const field=section.querySelector('input[aria-label="演示昵称"]');type(field,'临时用户');
   section.querySelector('button[type="submit"]').click();
   await wait(()=>section.textContent.includes('浏览器存储不可用'),'blocked storage failure feedback');
   if(!trigger.textContent.includes('临时用户'))throw Error('session-only save failed');
  }
  document.body.dataset.mockJourneyResult='pass';
 }catch(e){document.body.dataset.mockJourneyResult='fail:'+(e.message||e)}
})+')('+JSON.stringify(phase)+');</script></body>'));
 try{const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=42000','--window-size='+(phase==='logged-out'?'1024':'1440')+',900','--user-data-dir='+runProfile,'--dump-dom',new URL('/'+name,base).href],{encoding:'utf8',timeout:115000,maxBuffer:10000000});
 const result=r.stdout?.match(/data-mock-journey-result="([^"]+)"/)?.[1]||'missing';
 assert.equal(result,'pass',phase+': '+result+' stderr='+String(r.stderr||'').slice(-180));console.log('PASS '+phase+' real Chrome');
 }finally{try{fs.unlinkSync(name)}catch{}if(phase==='storage-denied')try{fs.rmSync(runProfile,{recursive:true,force:true})}catch{}}
}console.log('REA_MOCK_AUTH_CHROME_5_OF_5_PASS');
}finally{try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
