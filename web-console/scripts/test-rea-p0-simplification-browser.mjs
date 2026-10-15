import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3128/');
assert.equal(base.hostname,'127.0.0.1','local read-only browser only');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const file='qa-rea-p0-simplification.html';
const journey=async function(){
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const wait=async(fn,label)=>{for(let i=0;i<280;i++){const x=fn();if(x)return x;await sleep(100)}throw Error('timeout: '+label)};
 try{
   const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
   const go=async(label,selector)=>{const b=[...nav.querySelectorAll('button')].find(e=>e.getAttribute('aria-label')===label);if(!b)throw Error('nav '+label);b.click();return await wait(()=>document.querySelector(selector),label)};
   const home=await wait(()=>document.querySelector('#storyos-home-overview'),'home');
   if(!home.querySelector('[aria-label="创作快捷入口"]')||!home.querySelector('[aria-label="最近创作画廊"]'))throw Error('missing creator-first home');
   const manage=home.querySelector('details[aria-label="工作台完整管理与数据核对"]');
   if(!manage||manage.open||!manage.querySelector('[aria-label="工作台继续制作主列表"]'))throw Error('home management fold or safety data missing');
   manage.open=true;
   if(!manage.querySelector('[aria-label="正式作品 · Runtime 目录"]') && !manage.textContent.includes('正式作品'))throw Error('runtime provenance missing');
   manage.open=false;
   const library=await go('作品与项目','#series-library-view');
   const draft=library.querySelector('details[aria-label="草稿管理工具"]');
   const runtime=library.querySelector('details[aria-label="正式 Runtime 作品目录"]');
   if(!draft||!runtime||draft.open||runtime.open)throw Error('library admin tools not hidden by default');
   const search=await wait(()=>library.querySelector('input[aria-label="搜索故事标题、编号或类型"]'),'gallery search');
   if(!search)throw Error('story library search missing');
   draft.open=true;
   if(!draft.textContent.includes('导出草稿备份')||!draft.textContent.includes('保存到服务端'))throw Error('draft abilities lost');
   runtime.open=true;
   if(!runtime.textContent.includes('正式作品'))throw Error('runtime catalog inaccessible');
   const canvasPage=await go('故事制作','[aria-label="分镜与素材创作画布"]');
   const params=canvasPage.querySelector('details[aria-label="创作参数只读面板"]');
   if(!params||params.open||!params.textContent.includes('图片模型'))throw Error('parameters not correctly collapsed');
   const visual=canvasPage.querySelector('[aria-label="分镜视觉内容"]');
   const review=document.querySelector('[aria-label="逐帧审核检视区"]');
   const frames=document.querySelector('[aria-label="逐帧索引"]');
   if(!visual||!review||!frames)throw Error('canvas or reviewer not available');
   params.open=true;
   if(!params.textContent.includes('画幅'))throw Error('parameter detail lost');
   if(document.documentElement.scrollWidth>innerWidth+12)throw Error('horizontal overflow');
   document.body.dataset.p0Simplification='pass';
 }catch(error){document.body.dataset.p0Simplification='fail:'+String(error?.message||error)}
};
fs.writeFileSync(file,html.replace('</body>','<script>('+journey+')();</script></body>'));
try{
 for(const [name,width] of [['desktop',1440],['compact',1024]]){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-rea-p0-'));
  try{
   const r=spawnSync(chrome,['--headless=new','--disable-gpu','--no-sandbox','--disable-extensions','--disable-dev-shm-usage','--virtual-time-budget=35000','--window-size='+width+',900','--user-data-dir='+dir,'--dump-dom',new URL('/'+file,base).href],{encoding:'utf8',timeout:85000,maxBuffer:6500000});
   const mark=r.stdout?.match(/data-p0-simplification="([^"]+)"/)?.[1]||'missing';
   assert.equal(mark,'pass',name+': '+mark+' '+String(r.stderr||'').slice(-350));
   console.log('PASS P0 creator-first layout & preserved admin actions',name);
  }finally{fs.rmSync(dir,{recursive:true,force:true});}
 }
}finally{fs.rmSync(file,{force:true});}
console.log('REA_P0_CREATOR_SIMPLIFICATION_2_OF_2_PASS');
