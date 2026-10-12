import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','real local read-only only');
const catalog=await fetch(new URL('/api/v1/local-media/catalog',base)).then(r=>r.json());
assert.equal(catalog.data?.source,'local_workspace_approved_only');
const real=catalog.data.items.find(item=>item.frames?.length>=20);
assert.ok(real?.title,'20 approved images are required');
const dir=path.resolve('../.storyos-tmp/ui-qa/r27');fs.mkdirSync(dir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const cases=[
 {name:'approved-direct-frame-16',kind:'approved',width:1440},
 {name:'approved-last-frame-20',kind:'last',width:1440},
 {name:'compare-fast-jump-desktop',kind:'compare',width:1440},
 {name:'compare-fast-jump-compact',kind:'compare',width:1024},
 {name:'batch-status-fast-jump',kind:'batch',width:1366},
 {name:'review-navigate-linked',kind:'review',width:1366}
].map(c=>({...c,realTitle:real.title}));

async function scenario(c){
 try{
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const wait=async(fn,label)=>{for(let i=0;i<320;i++){const val=fn();if(val)return val;await sleep(85)}throw Error('timeout '+label)};
  const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
  const menu=name=>{const b=[...nav.querySelectorAll('button')].find(x=>x.textContent?.trim()===name);if(!b)throw Error('menu '+name);b.click()};
  const frameDrawer=async(no)=>{
    const body=await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-body'),'frame drawer');
    await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-header-title')?.textContent?.includes('Frame '+String(no).padStart(2,'0')),'frame '+no);
    return body;
  };
  const openApproved=async()=>{
    menu('作品与项目');
    const lib=await wait(()=>document.querySelector('#series-library-view'),'library');
    const search=await wait(()=>lib.querySelector('input[aria-label="搜索故事标题、编号或类型"]'),'search');
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(search,c.realTitle);
    search.dispatchEvent(new Event('input',{bubbles:true}));
    const card=await wait(()=>[...lib.querySelectorAll('button[aria-label^="预览作品"]')].find(x=>x.getAttribute('aria-label')?.includes(c.realTitle)&&x.querySelector('img[src^="/api/v1/local-media/images/"]')),'real card');
    card.click();
    const preview=await wait(()=>document.querySelector('.storyos-episode-preview-inspector .ant-drawer-body'),'preview');
    (await wait(()=>[...preview.querySelectorAll('button')].find(x=>x.textContent?.trim()==='进入故事制作'),'entry')).click();
    const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'canvas');
    (await wait(()=>canvas.querySelector('button[aria-label="检视已批准 Frame 1"]'),'Frame 1')).click();
    return await frameDrawer(1);
  };
  const strip=async()=>{
    const el=await wait(()=>document.querySelector('[aria-label="分镜序列缩略导航"]'),'frame filmstrip');
    await wait(()=>el.querySelectorAll('button[aria-label^="快速定位 Frame"]').length===20,'20 navigable frames');
    return el;
  };
  if(['approved','last','compare'].includes(c.kind)){
    const drawer=await openApproved();
    const nav=await strip();
    if(!nav.querySelector('img[src^="/api/v1/local-media/images/"]'))throw Error('real approved thumbnail absent');
    if(c.kind==='compare'){
      const pin=drawer.querySelector('button[aria-label="固定当前帧以对照"]');
      pin?.click();
    }
    const no=c.kind==='last'?20:16;
    const jump=nav.querySelector('button[aria-label="快速定位 Frame '+no+'"]');
    if(!jump)throw Error('frame shortcut '+no+' missing');
    jump.click();
    await frameDrawer(no);
    await wait(()=>nav.querySelector('[aria-current="true"]')?.getAttribute('aria-label')==='快速定位 Frame '+no,'current frame selection');
    await wait(()=>nav.scrollLeft>0,'horizontal filmstrip keeps selection visible');
    if(c.kind==='compare'){
      const images=await wait(()=>{const area=document.querySelector('[aria-label="双帧素材对照"]');const pics=[...area?.querySelectorAll('img[src^="/api/v1/local-media/images/"]')||[]];return pics.length===2?pics:null},'real two-image compare');
      if(images[0].src===images[1].src)throw Error('comparison sources identical');
      await wait(()=>images.every(img=>img.complete&&img.naturalWidth>0),'both comparison images decoded');
    }else if(c.kind==='last'){
      const next=drawer.querySelector('button[aria-label="下一帧"]');
      if(!next?.disabled)throw Error('Frame 20 should disable next');
    }else{
      const next=drawer.querySelector('button[aria-label="下一帧"]');
      next?.click();await frameDrawer(17);
      if(!nav.querySelector('button[aria-current="true"][aria-label="快速定位 Frame 17"]'))throw Error('filmstrip did not follow next-frame');
    }
    const inspector=document.querySelector('.storyos-creator-frame-inspector');
    if(inspector.getBoundingClientRect().width>innerWidth+4)throw Error('inspector spills beyond viewport');
  }else{
    menu('故事制作');
    const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'status canvas');
    if(canvas.querySelector('img[src^="/api/v1/local-media/images/"]'))throw Error('unapproved media leaked');
    if(c.kind==='batch'){
      (await wait(()=>canvas.querySelector('button[aria-label="检视批次 Frame 1"]'),'batch frame')).click();
    }else{
      const review=await wait(()=>document.querySelector('[aria-label="逐帧审核检视区"]'),'review');
      (await wait(()=>review.querySelector('button[aria-label^="检视审核 Frame"]'),'review jump')).click();
    }
    const drawer=await frameDrawer(1);
    const nav=await strip();
    if(nav.querySelector('img'))throw Error('no-evidence filmstrip must not use invented thumbnails');
    if(drawer.querySelector('button[aria-label="跳转下一待查帧"]'))throw Error('no recorded WARN/FAIL - should not invent attention navigation');
    nav.querySelector('button[aria-label="快速定位 Frame 16"]')?.click();
    await frameDrawer(16);
    if(drawer.querySelector('button[aria-label="固定当前帧以对照"]')?.disabled!==true)throw Error('no-image pin must remain disabled');
    await wait(()=>nav.scrollLeft>0,'batch shortcut scroll');
  }
  if(document.documentElement.scrollWidth>innerWidth+4)throw Error('viewport horizontal overflow');
  document.body.dataset.r27Result='pass';
 }catch(error){document.body.dataset.r27Result='fail:'+error.message;}
}

try{
 for(const c of cases){
  const filename='qa-r27-'+c.name+'.html';
  fs.writeFileSync(filename,html.replace('</body>','<script>('+scenario.toString()+')('+JSON.stringify(c)+');</script></body>'));
  const url=new URL('/'+filename,base).href;
  const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars',
    '--virtual-time-budget=39000','--window-size='+c.width+',900','--user-data-dir='+path.join(dir,'profile-'+c.name)];
  const dom=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:92000,maxBuffer:7000000});
  const result=dom.stdout?.match(/data-r27-result="([^"]+)"/)?.[1]||'missing';
  if(result!=='pass'){
    fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(dom.stdout||'').slice(-24000)+'\n'+(dom.stderr||'').slice(-1200));
    throw Error(c.name+' '+result);
  }
  const shot=path.join(dir,'storyos-r27-'+c.name+'.png');
  const screen=spawnSync(chrome,[...args,'--screenshot='+shot,url],{encoding:'utf8',timeout:92000});
  assert.equal(screen.status,0,'Chrome screenshot error for '+c.name);
  assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>7000,'missing screenshot '+c.name);
  console.log('PASS '+c.name+' '+c.width+'px, screenshot '+fs.statSync(shot).size+' bytes');
 }
 console.log('R27_FOUR_SLOT_FILMSTRIP_6_OF_6_PASS');
}finally{for(const c of cases)try{fs.unlinkSync('qa-r27-'+c.name+'.html')}catch{}}
