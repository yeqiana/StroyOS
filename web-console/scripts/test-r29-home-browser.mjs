import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';

const root=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(root.hostname,'127.0.0.1','R29 must inspect the actual local read-only console');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r29');
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
   const focus=await wait(()=>view.querySelector('[aria-label="创作焦点"]'),'creator first focus');
   const mainGrid=await wait(()=>view.querySelector('.storyos-home-episode-grid'),'full width episode table');
   const meta=view.querySelector('[aria-label="项目概况"]');
   const sidebar=view.querySelector('[aria-label="工作台关注事项与快捷入口"]');
   if(!meta||!sidebar)throw Error('creator focus provenance or contextual rail missing');
   if(mainGrid.getBoundingClientRect().width<view.getBoundingClientRect().width*.82)throw Error('episode list should retain full width');
   if(!view.querySelector('input[aria-label="搜索作品"]'))throw Error('search lost');
   await wait(()=>{
     const imgs=[...focus.querySelectorAll('img[src^="/api/v1/local-media/images/"]')];
     return imgs.length>=3&&imgs.every(img=>img.complete&&img.naturalWidth>0&&img.naturalHeight>0);
   },'3 authentic approved images must decode');
   const heroImage=focus.querySelector('button[aria-label^="打开焦点作品 "] img');
   if(!heroImage||heroImage.naturalWidth===0)throw Error('hero must contain decoded approved image');
   const focusedName=focus.querySelector('button[aria-label^="打开焦点作品 "]')?.getAttribute('aria-label')?.slice('打开焦点作品 '.length);
   if(!focusedName)throw Error('hero is not actionable');
   const options=view.querySelector('[aria-label="首页作品范围"]');
   if(!options||options.querySelectorAll('.ant-segmented-item').length!==3)throw Error('three list scopes missing');
   const approvedOption=[...options.querySelectorAll('.ant-segmented-item-label')].find(x=>x.textContent?.includes('有批准图片'));
   approvedOption?.click();
   await wait(()=>view.querySelector('.storyos-home-episode-grid .ant-table-tbody')?.querySelectorAll('tr.ant-table-row').length===3,'approved list actually filters to catalog items');
   const reset=[...options.querySelectorAll('.ant-segmented-item-label')].find(x=>x.textContent?.trim()==='全部');
   reset?.click();
   await wait(()=>view.querySelector('.storyos-home-episode-grid .ant-table-tbody')?.querySelectorAll('tr.ant-table-row').length>=8,'all episodes restored');
   const section=view.querySelector('[aria-label="平台生产阶段摘要"]');
   if(!section?.querySelector('details')||section.querySelector('details').open)throw Error('technical stage details must be collapsed by default');
   if(document.documentElement.scrollWidth>innerWidth+4)throw Error('document overflow on creator homepage');
   const heroAction=[...focus.querySelectorAll('button')].find(btn=>btn.textContent?.trim()==='继续制作');
   if(!heroAction)throw Error('creator direct action absent');
   heroAction.click();
   await wait(()=>document.querySelector('main')?.textContent?.includes(focusedName),'creator action opens actual story');
   const back=[...nav.querySelectorAll('button')].find(btn=>btn.textContent?.trim()==='工作台');
   if(!back)throw Error('return navigation missing');
   back.click();
   await wait(()=>document.querySelector('#storyos-home-overview'),'return home from creator');
   await wait(()=>{
     const images=[...document.querySelectorAll('#storyos-home-overview [aria-label="创作焦点"] img[src^="/api/v1/local-media/images/"]')];
     return images.length>=3&&images.every(img=>img.complete&&img.naturalWidth>0);
   },'home images decoded after return');
   const mainScroll=document.querySelector('main');
   mainScroll?.scrollTo({top:0,behavior:'instant'});
   await wait(()=>!mainScroll||mainScroll.scrollTop<4,'home screenshot reset to top');
   evidence='authentic creator hero, images decoded and direct story route';
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
 console.log('R29_CREATOR_HOME_3_WIDTH_PASS');
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
      const filename=path.join(dir,'storyos-r29-'+c.name+'-'+width+'.png');
      fs.writeFileSync(filename,Buffer.from(image.data,'base64'));
      assert.ok(fs.statSync(filename).size>9000,'Screenshot failed '+c.name+' '+width);
      console.log('PASS '+c.name+' '+width+'px · '+result.evidence+' · screenshot '+fs.statSync(filename).size+' bytes');
   }
 }finally{if(ws)ws.close();child.kill();}
}
console.log('R29_CREATOR_HOME_3_WIDTH_PASS');
