import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';

const root=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(root.hostname,'127.0.0.1','R30 must inspect the actual local read-only console');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r30');
fs.mkdirSync(dir,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const cases=[{name:'overview',menu:'工作台',selector:'#storyos-home-overview',heading:'工作台'}];

async function browserCase(c){
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const wait=async(fn,label)=>{for(let n=0;n<310;n++){const found=fn();if(found)return found;await sleep(85)}throw Error('timeout '+label)};
 const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
 const controls=[...document.querySelectorAll('button')];
 const menu=c.menu==='系统设置'?controls.find(x=>x.textContent?.trim()==='系统设置'):[...nav.querySelectorAll('button')].find(x=>x.textContent?.trim()===c.menu);
 if(!menu)throw Error('missing navigation menu '+c.menu);
 menu.click();
 const view=await wait(()=>document.querySelector(c.selector),'page '+c.name);
 await wait(()=>view.querySelector('h1')?.textContent?.trim()===c.heading,'page heading '+c.heading);
 let evidence='normal';
 if(c.name==='overview'){
   const quick=await wait(()=>view.querySelector('[aria-label="创作快捷入口"]'),'creator quick actions');
   const buttons=[...quick.querySelectorAll('button')];
   const create=buttons.find(b=>b.textContent?.trim()==='新建故事');
   const resume=buttons.find(b=>b.textContent?.trim()==='继续制作');
   const library=buttons.find(b=>b.textContent?.includes('查看素材'));
   if(!create||!resume||resume.disabled||!library)throw Error('three real creator actions missing');
   const recent=await wait(()=>view.querySelector('[aria-label="最近创作画廊"]'),'recent gallery');
   const covers=await wait(()=>{
     const images=[...recent.querySelectorAll('button[aria-label^="打开最近创作 "] img[src^="/api/v1/local-media/images/"]')];
     return images.length>=3&&images.every(img=>img.complete&&img.naturalWidth>0)?images:null;
   },'three real approved cover images decode');
   if(covers.length!==3)throw Error('unexpected approved image count');
   if(view.querySelector('[aria-label="创作焦点"]'))throw Error('old repeated hero layout still exists');
   if(!view.querySelector('[aria-label="项目概况"]')||!view.querySelector('[aria-label="工作台关注事项与快捷入口"]'))throw Error('operations metadata missing');
   const originalTable=await wait(()=>view.querySelector('.storyos-home-episode-grid'),'table workspace');
   if(originalTable.getBoundingClientRect().width<view.getBoundingClientRect().width*.8)throw Error('data area too narrow');
   const technical=await wait(()=>view.querySelector('[aria-label="平台生产阶段摘要"] details'),'technical evidence');
   if(technical.open)throw Error('technical evidence expanded by default');
   const mode=view.querySelector('[aria-label="作品管理显示方式"]');
   const scope=view.querySelector('[aria-label="首页作品范围"]');
   if(!mode||!scope||!view.querySelector('input[aria-label="搜索作品"]'))throw Error('list/gallery + filter controls missing');
   [...mode.querySelectorAll('.ant-segmented-item-label')].find(b=>b.textContent?.trim()==='画廊')?.click();
   await wait(()=>view.querySelectorAll('[aria-label="工作台作品管理画廊"] button[aria-label^="管理作品 "]').length>=8,'all works gallery');
   [...scope.querySelectorAll('.ant-segmented-item-label')].find(b=>b.textContent?.includes('有批准图片'))?.click();
   await wait(()=>view.querySelectorAll('[aria-label="工作台作品管理画廊"] button[aria-label^="管理作品 "]').length===3,'approved-only gallery');
   [...mode.querySelectorAll('.ant-segmented-item-label')].find(b=>b.textContent?.trim()==='列表')?.click();
   await wait(()=>view.querySelectorAll('.storyos-home-episode-grid .ant-table-tbody tr.ant-table-row').length===3,'approved-only list');
   [...scope.querySelectorAll('.ant-segmented-item-label')].find(b=>b.textContent?.trim()==='全部')?.click();
   await wait(()=>view.querySelectorAll('.storyos-home-episode-grid .ant-table-tbody tr.ant-table-row').length>=8,'reset list');
   const story=recent.querySelector('button[aria-label^="打开最近创作 "]')?.getAttribute('aria-label')?.replace('打开最近创作 ','');
   if(!story)throw Error('real story title absent');
   const search=view.querySelector('input[aria-label="搜索作品"]');
   const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;
   setter.call(search,story);
   search.dispatchEvent(new Event('input',{bubbles:true}));
   await wait(()=>view.querySelectorAll('.storyos-home-episode-grid .ant-table-tbody tr.ant-table-row').length===1,'search real title');
   setter.call(search,'');
   search.dispatchEvent(new Event('input',{bubbles:true}));
   await wait(()=>view.querySelectorAll('.storyos-home-episode-grid .ant-table-tbody tr.ant-table-row').length>=8,'restore all records');
   library.click();
   await wait(()=>document.querySelector('#series-library-view'),'navigate to asset library');
   const back=[...nav.querySelectorAll('button')].find(b=>b.textContent?.trim()==='工作台');
   back.click();
   await wait(()=>document.querySelector('#storyos-home-overview'),'return home from library');
   (await wait(()=>[...document.querySelectorAll('#storyos-home-overview [aria-label="创作快捷入口"] button')].find(b=>b.textContent?.trim()==='继续制作'),'resume action')).click();
   await wait(()=>document.querySelector('main')?.textContent?.includes(story),'resume opens correct real story');
   back.click();
   await wait(()=>document.querySelector('#storyos-home-overview'),'return home from story');
   await wait(()=>{
     const imgs=[...document.querySelectorAll('#storyos-home-overview [aria-label="最近创作画廊"] button[aria-label^="打开最近创作 "] img')];
     return imgs.length===3&&imgs.every(img=>img.complete&&img.naturalWidth>0);
   },'real gallery images after returning');
   const scroller=document.querySelector('main');
   scroller?.scrollTo({top:0,behavior:'instant'});
   await wait(()=>!scroller||scroller.scrollTop<4,'scroll restored to top for screenshot');
   evidence='3 creator actions + genuine approved gallery + table/gallery management + navigation';
 }
 await sleep(360);
 if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal viewport overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
 const main=document.querySelector('main');
 // CTA navigates to the actual story and back; use the newly mounted home node.
 const actual=(document.querySelector(c.selector)||view).getBoundingClientRect();
 if(actual.width<Math.min(360,(main?.clientWidth||innerWidth)*.75))throw Error('page is unexpectedly narrow');
 return {name:c.name,heading:c.heading,evidence,width:innerWidth,usedWidth:Math.round(actual.width)};
}

// Start a clean Chrome process for each width: page contexts on Windows can be replaced
// when a previous Chrome profile exits, even when a previous CDP test finished.
const widthArg=process.argv.find(arg=>arg.startsWith('--width='));
if(!widthArg){
 for(const width of [1440,1366,1024]){
   const result=spawnSync(process.execPath,[process.argv[1],'--width='+width],{stdio:'inherit',timeout:240000});
   if(result.status!==0)process.exit(result.status||1);
 }
 console.log('R30_CREATOR_HOME_3_WIDTH_PASS');
 process.exit(0);
}
const requestedWidth=Number(widthArg.slice('--width='.length));
assert.ok([1024,1366,1440].includes(requestedWidth),'supported viewport required');
for(const width of [requestedWidth]){
 const profile=path.join(dir,'chrome-profile-'+width+'-'+process.pid);
 const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--remote-debugging-port=0',
   '--window-size='+width+',900','--user-data-dir='+profile,root.href],{stdio:'ignore'});
 let ws;
 try{
   const portFile=path.join(profile,'DevToolsActivePort');
   let port=null;
   for(let i=0;i<180;i++){
     if(fs.existsSync(portFile)){
       try{const value=Number(fs.readFileSync(portFile,'utf8').split('\n')[0]);if(Number.isInteger(value)&&value>0){port=value;break}}catch(error){if(!['EBUSY','EACCES','ENOENT'].includes(error?.code))throw error}
     }
     await sleep(100);
   }
   assert.ok(port,'Chrome CDP port unavailable');
   let target;
   for(let i=0;i<180;i++){
     try{target=(await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json())).find(x=>x.type==='page'&&x.url.startsWith(root.href));if(target)break}catch{}
     await sleep(100);
   }
   assert.ok(target?.webSocketDebuggerUrl,'Chrome page unavailable');
   ws=new WebSocket(target.webSocketDebuggerUrl);
   await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true})});
   let sequence=0;const pending=new Map();
   ws.addEventListener('message',e=>{let value;try{value=JSON.parse(e.data)}catch{return}if(!value.id||!pending.has(value.id))return;const promise=pending.get(value.id);pending.delete(value.id);value.error?promise.reject(Error(value.error.message)):promise.resolve(value.result)});
   const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}))});
   await send('Runtime.enable');await send('Page.enable');
   // On narrow Windows headless Chrome, navigation can replace the first renderer context
   // immediately after CDP attaches. Wait for a stable document and retry only that transient.
   await sleep(1000);
   for(const c of cases){
      let response;
      for(let attempt=0;attempt<8;attempt++){
        try{
          response=await send('Runtime.evaluate',{expression:'('+browserCase.toString()+')('+JSON.stringify(c)+')',awaitPromise:true,returnByValue:true});
          break;
        }catch(error){
          if(attempt===7||!String(error).includes('Execution context was destroyed'))throw error;
          await sleep(550);
        }
      }
      if(!response)throw Error('Browser context never became available '+c.name+' '+width);
      if(response.exceptionDetails)throw Error('Browser '+c.name+' '+width+': '+(response.exceptionDetails.exception?.description||response.exceptionDetails.text));
      const result=response.result?.value;
      if(!result||result.name!==c.name)throw Error('Missing browser verification '+c.name+' at '+width);
      await sleep(550);
      const image=await send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
      const filename=path.join(dir,'storyos-r30-'+c.name+'-'+width+'.png');
      fs.writeFileSync(filename,Buffer.from(image.data,'base64'));
      assert.ok(fs.statSync(filename).size>9000,'Screenshot failed '+c.name+' '+width);
      console.log('PASS '+c.name+' '+width+'px · '+result.evidence+' · screenshot '+fs.statSync(filename).size+' bytes');
      // Capture the management section in both native views in this verified Chrome tab.
      for(const mode of ['list','gallery']){
        const scenario='(async()=>{const section=document.querySelector("[aria-label=\\"工作台继续制作主列表\\"]");if(!section)throw Error("management section missing");const panel=document.querySelector("[aria-label=\\"作品管理显示方式\\"]");const tab=[...panel.querySelectorAll(".ant-segmented-item-label")].find(x=>x.textContent?.trim()==='+JSON.stringify(mode==='list'?'列表':'画廊')+');if(!tab)throw Error("mode tab missing");tab.click();await new Promise(resolve=>setTimeout(resolve,380));section.scrollIntoView({block:"start",behavior:"instant"});await new Promise(resolve=>setTimeout(resolve,380));return {hasRows:!!section.querySelector(".storyos-home-episode-grid .ant-table-tbody tr.ant-table-row"),hasCards:!!section.querySelector("[aria-label=\\"工作台作品管理画廊\\"] button[aria-label^=\\"管理作品 \\"]"),scroll:document.querySelector("main")?.scrollTop||0}})()';
        const state=await send('Runtime.evaluate',{expression:scenario,awaitPromise:true,returnByValue:true});
        if(state.exceptionDetails)throw Error('R30 management '+mode+' Chrome exception: '+state.exceptionDetails.text);
        if(!state.result?.value?.[mode==='list'?'hasRows':'hasCards'])throw Error('R30 management '+mode+' view empty');
        const frame=await send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
        const pathMode=path.join(dir,'storyos-r30-management-'+mode+'-'+width+'.png');
        fs.writeFileSync(pathMode,Buffer.from(frame.data,'base64'));
        assert.ok(fs.statSync(pathMode).size>9000,'management screenshot missing');
      }
   }
 }finally{if(ws)ws.close();child.kill();}
}
console.log('R30_CREATOR_HOME_3_WIDTH_PASS');
