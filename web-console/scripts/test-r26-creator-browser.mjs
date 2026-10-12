import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','R26 screenshots require the real local read-only server');
const catalogRes=await fetch(new URL('/api/v1/local-media/catalog',base));
assert.equal(catalogRes.status,200,'real approved asset catalog unavailable');
const catalog=await catalogRes.json();
assert.equal(catalog.data?.source,'local_workspace_approved_only');
const real=catalog.data.items.find(item=>item.frames?.length>=10);
assert.ok(real?.title,'must test against a real ten-plus approved-frame story');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r26');fs.mkdirSync(dir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[
 {name:'creator-sequence-1440',width:1440,kind:'approved'},
 {name:'creator-dual-compare-1440',width:1440,kind:'compare'},
 {name:'creator-dual-compare-1024',width:1024,kind:'compare'},
 {name:'creator-review-jump-1366',width:1366,kind:'review'},
 {name:'creator-no-fake-1366',width:1366,kind:'no-image'},
 {name:'creator-compare-clear-1280',width:1280,kind:'clear'}
].map(c=>({...c,title:real.title}));

async function scenario(c){
 try{
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const wait=async(fn,label)=>{for(let i=0;i<290;i++){const value=fn();if(value)return value;await sleep(90)}throw Error('timeout '+label)};
  const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'navigation');
  const selectMenu=name=>{const button=[...nav.querySelectorAll('button')].find(b=>b.textContent?.trim()===name);if(!button)throw Error('menu '+name);button.click()};
  const openReal=async()=>{
    selectMenu('作品与项目');
    const library=await wait(()=>document.querySelector('#series-library-view'),'library');
    const search=await wait(()=>library.querySelector('input[aria-label="搜索故事标题、编号或类型"]'),'search');
    const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
    setter.call(search,c.title);search.dispatchEvent(new Event('input',{bubbles:true}));
    const card=await wait(()=>[...library.querySelectorAll('button[aria-label^="预览作品"]')].find(b=>b.getAttribute('aria-label')?.includes(c.title)&&b.querySelector('img[src^="/api/v1/local-media/images/"]')),'real approved gallery card');
    card.click();
    const drawer=await wait(()=>document.querySelector('.storyos-episode-preview-inspector .ant-drawer-body'),'episode preview');
    const enter=await wait(()=>[...drawer.querySelectorAll('button')].find(b=>b.textContent?.trim()==='进入故事制作'),'enter creator');
    enter.click();
    const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'creator canvas');
    await wait(()=>canvas.querySelectorAll('button[aria-label^="检视已批准 Frame"]').length>=10,'approved frame buttons');
    return canvas;
  };
  const checkDrawer=async(expected)=>{
    const drawer=await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-body'),'frame inspector');
    await wait(()=>document.querySelector('.storyos-creator-frame-inspector .ant-drawer-header-title')?.textContent?.includes('Frame '+String(expected).padStart(2,'0')),'frame '+expected);
    return drawer;
  };
  if(['approved','compare','clear'].includes(c.kind)){
    const canvas=await openReal();
    const first=canvas.querySelector('button[aria-label="检视已批准 Frame 1"]');
    first?.click();
    const drawer=await checkDrawer(1);
    if(!drawer.querySelector('img[src^="/api/v1/local-media/images/"]'))throw Error('approved image missing');
    if(c.kind==='approved'){
      const next=drawer.querySelector('button[aria-label="下一帧"]');
      if(!next||next.disabled)throw Error('next-frame button unavailable');
      next.click();
      await checkDrawer(2);
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
      await checkDrawer(3);
      document.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
      await checkDrawer(2);
      const prev=drawer.querySelector('button[aria-label="上一帧"]');prev?.click();
      await checkDrawer(1);
      if(!prev?.disabled)throw Error('first frame previous not disabled');
      if(!drawer.textContent.includes('1 / 20'))throw Error('frame count not displayed');
    }else{
      const pin=drawer.querySelector('button[aria-label="固定当前帧以对照"]');
      if(!pin||pin.disabled)throw Error('real image cannot be pinned');
      pin.click();
      await wait(()=>document.querySelector('[aria-label="分镜对照工具栏"]'),'persistent pin toolbar');
      const next=await wait(()=>drawer.querySelector('button[aria-label="下一帧"]'),'next frame');
      next.click();
      await checkDrawer(2);
      const comparison=await wait(()=>document.querySelector('[aria-label="双帧素材对照"]'),'two-source comparison');
      const images=[...comparison.querySelectorAll('img[src^="/api/v1/local-media/images/"]')];
      if(images.length!==2||images[0].src===images[1].src)throw Error('side-by-side real images not distinct');
      await wait(()=>images.every(image=>image.complete&&image.naturalWidth>0),'both real comparison images decoded');
      if(document.querySelector('.storyos-creator-frame-inspector').getBoundingClientRect().width>innerWidth+4)throw Error('compare drawer overflows viewport');
      if(c.kind==='clear'){
        const close=drawer.querySelector('button[aria-label="取消固定对照帧"]');
        close?.click();
        await wait(()=>!document.querySelector('[aria-label="双帧素材对照"]'),'comparison dismissed');
        if(document.querySelector('[aria-label="分镜对照工具栏"]'))throw Error('persistent pin not cleared');
        if(drawer.querySelectorAll('img[alt^="Frame "][src^="/api/v1/local-media/images/"]').length!==1)throw Error('single inspected source image not restored');
      }
    }
  }else{
    selectMenu('故事制作');
    const canvas=await wait(()=>document.querySelector('[aria-label="分镜与素材创作画布"]'),'unapproved creator canvas');
    if(canvas.querySelector('img[src^="/api/v1/local-media/images/"]'))throw Error('unapproved canvas leaked approved image');
    if(c.kind==='review'){
      const review=await wait(()=>document.querySelector('[aria-label="逐帧审核检视区"]'),'review panel');
      const jump=await wait(()=>review.querySelector('button[aria-label^="检视审核 Frame"]'),'review jump');
      const no=Number(jump.getAttribute('aria-label')?.match(/(\d+)$/)?.[1]);
      if(!no)throw Error('review frame identity absent');
      jump.click();
      const drawer=await checkDrawer(no);
      if(!drawer.textContent.includes('审核结论'))throw Error('review verdict not linked into inspector');
      if(!drawer.textContent.includes('PASS')&&!drawer.textContent.includes('WARN')&&!drawer.textContent.includes('FAIL'))throw Error('review verdict missing');
      if(!drawer.textContent.includes('工作区状态快照'))throw Error('review evidence source missing');
    }else{
      const first=await wait(()=>canvas.querySelector('button[aria-label^="检视批次 Frame"]'),'batch status frame');
      first.click();
      const drawer=await checkDrawer(1);
      if(!drawer.textContent.includes('尚无可验证的 Frame 图片'))throw Error('unverified frame invented a picture');
      const pin=drawer.querySelector('button[aria-label="固定当前帧以对照"]');
      if(!pin?.disabled)throw Error('unverified image must not be pinnable');
      const next=drawer.querySelector('button[aria-label="下一帧"]');
      next?.click();await checkDrawer(2);
      if(document.querySelector('[aria-label="双帧素材对照"]'))throw Error('unverified compare appeared');
    }
  }
  if(document.documentElement.scrollWidth>innerWidth+4)throw Error('document horizontal overflow');
  document.body.dataset.r26Result='pass';
 }catch(error){document.body.dataset.r26Result='fail:'+error.message;}
}

try{
  for(const c of cases){
    const page='qa-r26-'+c.name+'.html';
    fs.writeFileSync(page,html.replace('</body>','<script>('+scenario.toString()+')('+JSON.stringify(c)+');</script></body>'));
    const url=new URL('/'+page,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars',
      '--virtual-time-budget=37000','--window-size='+c.width+',900','--user-data-dir='+path.join(dir,'profile-'+c.name)];
    const dump=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:92000,maxBuffer:7200000});
    const state=dump.stdout?.match(/data-r26-result="([^"]+)"/)?.[1]||'missing';
    if(state!=='pass'){
      fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(dump.stdout||'').slice(-23000)+'\n'+(dump.stderr||'').slice(-1200));
      throw Error(c.name+' '+state);
    }
    const shot=path.join(dir,'storyos-r26-'+c.name+'.png');
    // Screenshot is a separate Chrome run: allow the interactive drawer to finish opening
    // on slower narrow viewports, rather than capturing an intermediate canvas state.
    const screenshotArgs=args.map(item=>item.startsWith('--virtual-time-budget=')?'--virtual-time-budget=80000':item);
    const result=spawnSync(chrome,[...screenshotArgs,'--screenshot='+shot,url],{encoding:'utf8',timeout:112000});
    assert.equal(result.status,0,'browser screenshot failed for '+c.name);
    assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>7000,'screenshot missing '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px, real Chrome screenshot '+fs.statSync(shot).size+' B');
  }
  console.log('R26_FOUR_SLOT_CREATOR_INSPECTOR_6_OF_6_PASS');
}finally{
  for(const c of cases)try{fs.unlinkSync('qa-r26-'+c.name+'.html')}catch{}
}