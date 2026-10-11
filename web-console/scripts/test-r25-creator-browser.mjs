import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base = new URL(process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/');
assert.ok(['127.0.0.1','localhost'].includes(base.hostname),'R25 uses real local evidence only');
const catalogResponse=await fetch(new URL('/api/v1/local-media/catalog',base));
assert.equal(catalogResponse.status,200,'approved media API must be readable');
const catalog=await catalogResponse.json();
assert.equal(catalog?.data?.source,'local_workspace_approved_only');
const realMedia=(catalog?.data?.items||[]).find(item=>item.frames?.length>=1);
assert.ok(realMedia?.title,'a real approved-media episode is needed for evidence screenshot');

const chrome=process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const reportDir=path.resolve('../.storyos-tmp/ui-qa/r25');
fs.mkdirSync(reportDir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[
  {name:'library-gallery',width:1366,menu:'作品与项目'},
  {name:'library-preview',width:1280,menu:'作品与项目'},
  {name:'creator-approved-frame',width:1440,menu:'作品与项目'},
  {name:'creator-empty-evidence',width:1366,menu:'故事制作'},
  {name:'creator-compact',width:1024,menu:'故事制作'},
  {name:'library-list-compat',width:1280,menu:'作品与项目'}
].map(c=>({...c,realTitle:realMedia.title}));

async function browserScenario(c){
  try {
    const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
    const wait=async(fn,label)=>{for(let i=0;i<270;i++){const found=fn();if(found)return found;await delay(90);}throw Error('timeout '+label);};
    const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
    const target=[...nav.querySelectorAll('button')].find(b=>b.textContent?.trim()===c.menu);
    if(!target)throw Error('menu '+c.menu);
    target.click();
    const searchReal=async()=>{
      const view=await wait(()=>document.querySelector('#series-library-view'),'series');
      const search=await wait(()=>view.querySelector('input[aria-label="搜索故事标题、编号或类型"]'),'search');
      const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
      set.call(search,c.realTitle);
      search.dispatchEvent(new Event('input',{bubbles:true}));
      return await wait(()=>[...view.querySelectorAll('button[aria-label^="预览作品"]')].find(b=>b.getAttribute('aria-label')?.includes(c.realTitle)),'matching real media card');
    };
    if(c.name==='library-gallery'){
      const view=await wait(()=>document.querySelector('#series-library-view'),'library');
      const gallery=await wait(()=>view.querySelector('[aria-label="作品封面画廊"]'),'gallery');
      await wait(()=>gallery.querySelectorAll('button[aria-label^="预览作品"]').length>=8,'gallery rows');
      if(!view.textContent.includes('封面画廊'))throw Error('gallery switch missing');
      const closed=gallery.querySelectorAll('img[src^="/api/v1/local-media/images/"]');
      if(!closed.length){
        const card=await searchReal();
        await wait(()=>card.querySelector('img[src^="/api/v1/local-media/images/"]'),'approved image loaded');
      }
      const search=view.querySelector('input[aria-label="搜索故事标题、编号或类型"]');
      if(search?.value){const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;set.call(search,'');search.dispatchEvent(new Event('input',{bubbles:true}));}
      await wait(()=>gallery.querySelectorAll('button[aria-label^="预览作品"]').length>=8,'restored gallery');
      await wait(()=>gallery.querySelectorAll('img[src^="/api/v1/local-media/images/"]').length>=2,'gallery real thumbnails');
      if(document.querySelector('.storyos-episode-preview-inspector'))throw Error('preview should open only on request');
    }else if(c.name==='library-preview'||c.name==='creator-approved-frame'){
      const card=await searchReal();
      await wait(()=>card.querySelector('img[src^="/api/v1/local-media/images/"]'),'approved thumbnail loaded');
      card.click();
      const preview=await wait(()=>document.querySelector('.storyos-episode-preview-inspector .ant-drawer-body'),'episode preview');
      await wait(()=>preview.textContent?.includes('已批准素材')&&preview.textContent?.includes(c.realTitle),'episode evidence');
      const img=preview.querySelector('img[src^="/api/v1/local-media/images/"]');
      if(!img)throw Error('episode preview missing approved cover');
      if(c.name==='creator-approved-frame'){
        const open=[...preview.querySelectorAll('button')].find(b=>b.textContent?.trim()==='进入故事制作');
        if(!open)throw Error('enter creator button missing');
        open.click();
        const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'creator canvas');
        await wait(()=>canvas.querySelectorAll('button[aria-label^="检视已批准 Frame"]').length>=10,'approved frames');
        const param=canvas.querySelector('[aria-label="创作参数只读面板"]');
        if(!param||!param.textContent?.includes('图片模型'))throw Error('creator parameter rail missing');
        const btn=canvas.querySelector('button[aria-label^="检视已批准 Frame"]');
        btn.click();
        const frame=await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-body'),'creator frame');
        await wait(()=>frame.querySelector('img[src^="/api/v1/local-media/images/"]'),'real frame image');
        if(!frame.textContent.includes('已批准素材'))throw Error('frame provenance missing');
        const elevated=frame.closest('.ant-drawer-content');
        if(elevated && getComputedStyle(elevated).backgroundColor==='rgb(255, 255, 255)')throw Error('creator inspector is using incorrect light theme');
        if(document.querySelector('details[aria-label="生产阶段与制作指标"]')?.open)throw Error('full runtime diagnostics must default collapsed');
      }
    }else if(c.name==='creator-empty-evidence'||c.name==='creator-compact'){
      const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'creator canvas');
      const review=await wait(()=>document.querySelector('[aria-label="逐帧审核检视区"]'),'reviews');
      const params=canvas.querySelector('[aria-label="创作参数只读面板"]');
      if(!params||!params.textContent?.includes('画幅'))throw Error('missing read-only creative controls');
      if(!canvas.querySelector('.ant-segmented'))throw Error('canvas content switch missing');
      if(!canvas.querySelector('button[aria-label^="检视批次 Frame"]')&&!canvas.querySelector('button[aria-label^="检视已批准 Frame"]'))throw Error('no frame selection');
      const split=canvas.parentElement;
      if(c.width>=1280){
        const a=canvas.getBoundingClientRect(),b=review.getBoundingClientRect();
        if(Math.abs(a.top-b.top)>6)throw Error('review not aligned with canvas');
      }
      if(!split?.getAttribute('aria-label')?.includes('当前批次与审核双栏工作区'))throw Error('main structure changed');
      if(!document.querySelector('details[aria-label="生产阶段与制作指标"]'))throw Error('runtime evidence access missing');
      if(c.name==='creator-empty-evidence'){
        const first=canvas.querySelector('button[aria-label^="检视批次 Frame"]')||canvas.querySelector('button[aria-label^="检视已批准 Frame"]');
        first.click();
        const drawer=await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-body'),'frame details');
        await wait(()=>drawer.textContent?.includes('帧编号'),'frame metadata');
        const close=document.querySelector('.storyos-creator-frame-inspector .ant-drawer-close');
        close?.click();
        await wait(()=>!document.querySelector('.storyos-creator-frame-inspector'),'close frame inspector');
      }
    }else if(c.name==='library-list-compat'){
      const view=await wait(()=>document.querySelector('#series-library-view'),'library');
      const option=await wait(()=>[...view.querySelectorAll('.ant-segmented-item-label')].find(el=>el.textContent?.trim()==='列表'),'list choice');
      option.click();
      await wait(()=>view.querySelector('.ant-table-tbody tr'),'list table');
      if(view.querySelector('[aria-label="作品封面画廊"]'))throw Error('gallery visible in list mode');
      if(!view.querySelector('.ant-pagination'))throw Error('original list pagination missing');
      if(!view.querySelector('button[aria-label^="打开故事 "]'))throw Error('original story link missing');
      const project=[...document.querySelectorAll('[aria-label="项目列表"] button')].find(b=>b.textContent?.includes('项目空间'));
      if(!project||project.getAttribute('aria-expanded')!=='false')throw Error('project tree not collapsed by default');
      project.click();
      await wait(()=>project.getAttribute('aria-expanded')==='true','project tree expanded');
    }
    if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal overflow');
    document.body.dataset.r25Result='pass';
  }catch(e){
    document.body.dataset.r25Result='fail:'+e.message;
  }
}

try{
  for(const c of cases){
    const page='qa-r25-'+c.name+'.html';
    fs.writeFileSync(page,html.replace('</body>','<script>('+browserScenario.toString()+')('+JSON.stringify(c)+');</script></body>'));
    const url=new URL('/'+page,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars',
      '--virtual-time-budget=35000','--window-size='+c.width+',900','--user-data-dir='+path.join(reportDir,'profile-'+c.name)];
    const result=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:7500000});
    const state=result.stdout?.match(/data-r25-result="([^"]+)"/)?.[1]||'missing';
    if(state!=='pass'){
      fs.writeFileSync(path.join(reportDir,'failure-'+c.name+'.txt'),(result.stdout||'').slice(-21000)+'\n'+(result.stderr||'').slice(-1250));
      throw Error(c.name+' '+state);
    }
    const screenshot=path.join(reportDir,'storyos-r25-'+c.name+'.png');
    const shot=spawnSync(chrome,[...args,'--screenshot='+screenshot,url],{encoding:'utf8',timeout:85000});
    assert.equal(shot.status,0,'Chrome screenshot failed for '+c.name);
    assert.ok(fs.existsSync(screenshot)&&fs.statSync(screenshot).size>7000,'screenshot missing '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px; screenshot '+fs.statSync(screenshot).size+' B');
  }
  console.log('R25_CREATOR_FOUR_SLOTS_REAL_BROWSER_6_OF_6_PASS');
}finally{
  for(const c of cases)try{fs.unlinkSync('qa-r25-'+c.name+'.html')}catch{}
}
