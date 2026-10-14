import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3114/');assert.equal(base.hostname,'127.0.0.1');
const catalog=await fetch(new URL('/api/v1/local-media/catalog',base)).then(r=>r.json());
assert.equal(catalog.data?.source,'local_workspace_approved_only');
const media=catalog.data.items.find(x=>x.frames?.length>=2);assert.ok(media,'requires two real approved frames');
const source=media.frames[0],target=media.frames.find(f=>f.frame!==source.frame);
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-rea-link-'));
const html=fs.readFileSync('index.html','utf8');
const scenario=async function(c){
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 const wait=async(fn,label)=>{for(let i=0;i<320;i++){const v=fn();if(v)return v;await sleep(85)}throw Error('timeout '+label)};
 try {
  const main=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'main nav');
  const lib=[...main.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='作品与项目');
  if(!lib)throw Error('missing project library');
  lib.click();
  const view=await wait(()=>document.querySelector('#series-library-view'),'library');
  const search=await wait(()=>view.querySelector('input[aria-label="搜索故事标题、编号或类型"]'),'search');
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(search,c.title);
  search.dispatchEvent(new Event('input',{bubbles:true}));
  const card=await wait(()=>[...view.querySelectorAll('button[aria-label^="预览作品"]')].find(b=>b.getAttribute('aria-label')?.includes(c.title)&&b.querySelector('img[src^="/api/v1/local-media/images/"]')),'real approved card');
  card.click();
  const preview=await wait(()=>document.querySelector('.storyos-episode-preview-inspector .ant-drawer-body'),'preview');
  const enter=await wait(()=>[...preview.querySelectorAll('button')].find(b=>b.textContent?.trim()==='进入故事制作'),'enter workbench');
  enter.click();
  const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'canvas');
  const toolNav=await wait(()=>document.querySelector('nav[aria-label="创作工具快捷导航"]'),'compact tools');
  const labels=[...toolNav.querySelectorAll('button')].map(b=>b.textContent?.trim()||'');
  for(const t of ['帧定位','素材画布','审核记录','参考关联'])if(!labels.some(x=>x.startsWith(t)))throw Error('missing compact tool '+t);
  if(!document.querySelector('#storyos-creator-frame-index')||!document.querySelector('#storyos-creator-review')||!document.querySelector('#storyos-creator-canvas'))throw Error('missing navigation target');
  const source=Number(c.source), target=Number(c.target);
  const select=await wait(()=>canvas.querySelector('button[aria-label="检视已批准 Frame '+target+'"]'),'target frame');
  if(c.caseName==='create'){
   const pin=await wait(()=>canvas.querySelector('button[aria-label="固定已批准 Frame '+source+' 以对照"]'),'source pin');
   pin.click();
   await wait(()=>document.querySelector('[aria-label="分镜对照工具栏"]'),'pin toolbar');
  }
  select.click();
  const inspector=await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-body'),'target inspector');
  const section=await wait(()=>inspector.querySelector('section[aria-label="帧级参考素材草稿"]'),'reference draft');
  if(!section.textContent.includes('未提交生产')||!section.textContent.includes('不代表此帧生成时实际使用'))throw Error('authority boundary missing');
  if(!section.querySelector('[aria-label="为 Frame '+target+' 选择参考素材"]'))throw Error('trusted source picker missing');
  const k=Object.keys(localStorage).find(k=>k.startsWith('storyos:reference-draft:v1:'));
  if(c.caseName==='create'){
   if(k)throw Error('unexpected existing plan');
   const action=[...section.querySelectorAll('button')].find(b=>b.textContent?.includes('将固定 Frame '+source+' 设为参考草稿'));
   if(!action)throw Error('pin to reference action absent');
   action.click();
   await wait(()=>section.querySelector('[aria-label="已选参考素材草稿"]'),'linked preview');
   const lineage=await wait(()=>section.querySelector('[aria-label="参考素材来源关系"]'),'reference lineage');
   if(!lineage.textContent.includes('本机候选')||!lineage.textContent.includes('生产未提交')||!lineage.textContent.includes('Provider 使用未验证'))throw Error('asset lineage authority states absent');
   if(!lineage.textContent.includes('源图 SHA 待核验'))throw Error('source SHA premature verification');
   const proofButton=[...section.querySelectorAll('button')].find(b=>b.textContent?.includes('核验源图 SHA-256'));
   if(!proofButton)throw Error('source fingerprint action missing');
   proofButton.click();
   const proof=await wait(()=>section.querySelector('[aria-label="参考源图内容核验"] [role="status"]'),'source fingerprint receipt');
   if(!/[a-f0-9]{64}/.test(proof.textContent||'')||!proof.textContent.includes('未提交生产')||!proof.textContent.includes('未确认生图时使用'))throw Error('source proof authority boundary violated');
   await wait(()=>lineage.textContent.includes('源图 SHA 已核验'),'lineage proof updated');
   const key=Object.keys(localStorage).find(k=>k.startsWith('storyos:reference-draft:v1:'));
   if(!key)throw Error('draft did not persist');
   const data=JSON.parse(localStorage.getItem(key));
   if(data[target]?.sourceFrame!==source || data[target]?.sourceUrl!==c.sourceUrl)throw Error('stored source identity mismatch');
   if(!toolNav.textContent.includes('1 草稿'))throw Error('draft count missing');
   if(![...document.querySelectorAll('#storyos-creator-frame-index button')].find(x=>x.getAttribute('aria-label')?.startsWith('定位第 '+target+' 帧')&&x.querySelector('[aria-label="有本地参考草稿"]')))throw Error('target badge missing');
  } else {
   await wait(()=>section.querySelector('[aria-label="已选参考素材草稿"]'),'persisted reference');
   if(!section.textContent.includes('仅拟引用'))throw Error('draft misrepresented');
   const remove=[...section.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='移除 Frame '+target+' 的参考素材草稿');
   if(!remove)throw Error('remove action absent: '+[...section.querySelectorAll('button')].map(b=>b.outerHTML.slice(0,240)).join(' | '));
   remove.click();
   await wait(()=>!section.querySelector('[aria-label="已选参考素材草稿"]'),'removed');
   if(Object.keys(localStorage).some(k=>k.startsWith('storyos:reference-draft:v1:')))throw Error('local draft key not removed');
   if(toolNav.textContent.includes('1 草稿'))throw Error('count did not clear');
  }
  document.body.dataset.reaCompactResult='pass';
 } catch(e){ document.body.dataset.reaCompactResult='fail:'+e.message; }
};
try {
  for(const caseName of ['create','reload']) {
    const c={caseName,title:media.title,source:source.frame,target:target.frame,sourceUrl:source.url};
    const entry='qa-rea-compact-'+caseName+'.html';
    fs.writeFileSync(entry,html.replace('</body>','<script>('+scenario.toString()+')('+JSON.stringify(c)+');</script></body>'));
    try {
      const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=45000','--window-size=1280,900','--user-data-dir='+profile,'--dump-dom',new URL('/'+entry,base).href],{encoding:'utf8',timeout:110000,maxBuffer:8500000});
      const state=r.stdout?.match(/data-rea-compact-result="([^"]+)"/)?.[1]||'missing';
      assert.equal(state,'pass',caseName+' failed: '+state+' '+(r.stderr||'').slice(-450));
      console.log('PASS '+caseName+' real-media reference draft + compact tools');
    }finally{try{fs.unlinkSync(entry)}catch{}}
  }
  console.log('REA_COMPACT_REFERENCE_BROWSER_2_OF_2_PASS');
}finally{try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}