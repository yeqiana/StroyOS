import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3112/');assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const dir=path.resolve('../.storyos-tmp/ui-qa/rea-interaction-icons');
fs.mkdirSync(dir,{recursive:true});
const cases=[{"caseName":"home-icons","width":1440},{"caseName":"gallery","width":1440},{"caseName":"list-preview","width":1280},{"caseName":"list-direct","width":1024}];
const validate=async function (c) {
  const wait=async(fn,label)=>{for(let i=0;i<320;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,80))}throw Error('timeout '+label)};
  try {
    const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'main navigation');
    if(!nav.querySelector('button[aria-label="故事制作"] svg.lucide-book-open-text'))throw Error('story icon must be book, not video');
    const library=[...nav.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='作品与项目');
    if(!library)throw Error('library route missing');
    if(c.caseName==='home-icons'){
      const home=await wait(()=>document.querySelector('#storyos-home-overview'),'home');
      const mode=await wait(()=>home.querySelector('[aria-label="作品管理显示方式"]'),'home toggle');
      if(!mode.querySelector('svg.lucide-list')||!mode.querySelector('svg.lucide-images'))throw Error('home view mode icons missing');
      const gallery=[...mode.querySelectorAll('.ant-segmented-item-label')].find(e=>e.textContent?.trim()==='画廊');
      if(!gallery)throw Error('gallery switch missing');
      gallery.click();
      await wait(()=>home.querySelector('[aria-label="工作台作品管理画廊"]'),'home gallery');
      document.body.dataset.reaUi='pass';
      return;
    }
    library.click();
    const view=await wait(()=>document.querySelector('#series-library-view'),'library');
    const display=await wait(()=>view.querySelector('[aria-label="作品显示方式"]'),'library toggle');
    if(!display.querySelector('svg.lucide-images')||!display.querySelector('svg.lucide-list'))throw Error('library mode icons missing');
    if(c.caseName!=='gallery'){
      const list=[...display.querySelectorAll('.ant-segmented-item-label')].find(n=>n.textContent?.trim()==='列表');
      if(!list)throw Error('list option missing');
      list.click();
      await wait(()=>view.querySelector('button[aria-label^="打开故事 "]'),'library table');
      const direct=view.querySelector('button[aria-label^="打开故事 "]');
      if(!direct?.title.includes('直接进入'))throw Error('direct entry ambiguous');
      if(c.caseName==='list-direct'){
        direct.click();
        await wait(()=>nav.querySelector('button[aria-current="page"]')?.getAttribute('aria-label')==='故事制作','direct workbench');
        if(document.querySelector('.storyos-episode-preview-inspector.ant-drawer-open'))throw Error('direct unexpectedly opened preview');
        document.body.dataset.reaUi='pass';
        return;
      }
      const tr=direct.closest('tr');
      const preview=[...tr.querySelectorAll('button')].find(n=>n.textContent?.trim()==='预览');
      if(!preview||!preview.querySelector('svg.lucide-eye'))throw Error('table preview action absent');
      preview.click();
    } else {
      const card=await wait(()=>view.querySelector('button[aria-label^="预览作品 "] img[src^="/api/v1/local-media/images/"]')?.closest('button'),'approved gallery card');
      if(!card.querySelector('svg.lucide-eye'))throw Error('gallery preview icon missing');
      card.click();
    }
    const inspector=await wait(()=>document.querySelector('.storyos-episode-preview-inspector .ant-drawer-body'),'readonly inspector');
    if(!inspector.textContent.includes('已批准素材'))throw Error('approved count/evidence label missing');
    const enter=await wait(()=>[...inspector.querySelectorAll('button')].find(b=>b.textContent?.trim()==='进入故事制作'),'explicit entry');
    if(!enter.querySelector('svg.lucide-arrow-up-right'))throw Error('entry icon missing');
    if(!view.isConnected)throw Error('opening preview lost background workspace');
    if(c.caseName==='list-preview'){
      enter.click();
      await wait(()=>nav.querySelector('button[aria-current="page"]')?.getAttribute('aria-label')==='故事制作','inspector explicit entry');
      if(document.querySelector('.storyos-episode-preview-inspector.ant-drawer-open'))throw Error('inspector remained open after entry');
    }
    const font=getComputedStyle(nav.querySelector('button[aria-label="故事制作"] svg')).strokeWidth;
    if(font!=='1.75px'&&font!=='1.75')throw Error('lucide stroke weight drift '+font);
    if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal overflow');
    document.body.dataset.reaUi='pass';
  } catch(e) {document.body.dataset.reaUi='fail:'+String(e.message||e)}
};
for(const c of cases){
 const profile=fs.mkdtempSync(path.join(os.tmpdir(),'rea-storyos-icons-'));
 const entry='qa-rea-interaction-'+c.caseName+'.html';
 fs.writeFileSync(entry,html.replace('</body>','<script>('+validate.toString()+')('+JSON.stringify(c)+');</script></body>'));
 const url=new URL('/'+entry,base).href;
 const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-extensions','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=32000','--window-size='+c.width+',900','--user-data-dir='+profile];
 try{
  const r=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:8500000});
  const mark=r.stdout?.match(/data-rea-ui="([^"]+)"/)?.[1]||'missing';
  assert.equal(mark,'pass',c.caseName+' failed: '+mark+' '+(r.stderr||'').slice(-250));
  if(c.caseName==='gallery'||c.caseName==='list-preview'){
   const png=path.join(dir,'storyos-'+c.caseName+'.png');
   const shot=spawnSync(chrome,[...args,'--screenshot='+png,url],{encoding:'utf8',timeout:80000});
   assert.ok(shot.status===0&&fs.existsSync(png)&&fs.statSync(png).size>9000,'screenshot '+c.caseName);
  }
  console.log('PASS '+c.caseName+' '+c.width+'px interactive Chrome');
 }finally{try{fs.unlinkSync(entry)}catch{}try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
}
console.log('REA_INTERACTION_ICON_CHROME_4_OF_4_PASS');
