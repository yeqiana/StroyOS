import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';

const root=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(root.hostname,'127.0.0.1','R32 must inspect the actual local read-only console');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r32');
fs.mkdirSync(dir,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const cases=[{name:'draft',menu:'工作台',selector:'#storyos-home-overview',heading:'工作台'}];

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
 if(c.name==='draft'){
   const create=await wait(()=>[...view.querySelectorAll('button')].find(x=>x.textContent?.trim()==='新建故事'),'new story button');
   const count=JSON.parse(localStorage.getItem('storyos_local_story_drafts_v1')||'[]').length;
   create.click();
   const draft=await wait(()=>{
     const all=JSON.parse(localStorage.getItem('storyos_local_story_drafts_v1')||'[]');
     return all.length===count+1?all[all.length-1]:null;
   },'saved local story draft');
   if(!draft.id.startsWith('ep-home-')||!draft.title)throw Error('created draft identity is invalid');
   if(!draft.updatedAt||!Number.isFinite(Date.parse(draft.updatedAt)))throw Error('new draft has non-sortable updatedAt');
   await wait(()=>document.body.textContent?.includes(draft.title)&&nav.querySelector('button[aria-label="故事制作"][aria-current="page"]'),'draft selected in creator workbench header');
   const homeButton=await wait(()=>[...nav.querySelectorAll('button')].find(x=>x.textContent?.trim()==='工作台'),'home nav');
   homeButton.click();
   const home=await wait(()=>document.querySelector('#storyos-home-overview'),'back to home');
   const first=await wait(()=>home.querySelector('.storyos-home-episode-grid tr.ant-table-row'),'first story row');
   if(!first.textContent?.includes(draft.title))throw Error('new draft is not first in recently updated stories');
   if(!home.querySelector('input[aria-label="搜索作品"]'))throw Error('workbench search absent');
   evidence='new local draft '+draft.id+' sorts first and is persisted';
 }
 await sleep(360);
 if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal viewport overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
 const main=document.querySelector('main');
 const actual=(document.querySelector(c.selector)||view).getBoundingClientRect();
 if(actual.width<Math.min(360,(main?.clientWidth||innerWidth)*.75))throw Error('page is unexpectedly narrow');
 return {name:c.name,heading:c.heading,evidence,width:innerWidth,usedWidth:Math.round(actual.width)};
}

// Start a clean Chrome process for each width: page contexts on Windows can be replaced
// when a previous Chrome profile exits, even when a previous CDP test finished.
const widthArg=process.argv.find(arg=>arg.startsWith('--width='));
if(!widthArg){
 for(const width of [1440]){
   const result=spawnSync(process.execPath,[process.argv[1],'--width='+width],{stdio:'inherit',timeout:240000});
   if(result.status!==0)process.exit(result.status||1);
 }
 console.log('R32_LOCAL_DRAFT_SORT_1_OF_1_PASS');
 process.exit(0);
}
const requestedWidth=Number(widthArg.slice('--width='.length));
assert.ok([1440].includes(requestedWidth),'supported viewport required');
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
      const filename=path.join(dir,'storyos-r32-'+c.name+'-'+width+'.png');
      fs.writeFileSync(filename,Buffer.from(image.data,'base64'));
      assert.ok(fs.statSync(filename).size>9000,'Screenshot failed '+c.name+' '+width);
      console.log('PASS '+c.name+' '+width+'px · '+result.evidence+' · screenshot '+fs.statSync(filename).size+' bytes');
      await send('Page.reload',{ignoreCache:true});
      await sleep(900);
      const persisted=await send('Runtime.evaluate',{expression:'(async()=>{const sleep=ms=>new Promise(r=>setTimeout(r,ms));for(let i=0;i<240;i++){const first=document.querySelector("#storyos-home-overview .storyos-home-episode-grid tr.ant-table-row");if(first){const drafts=JSON.parse(localStorage.getItem("storyos_local_story_drafts_v1")||"[]");return {title:drafts[drafts.length-1]?.title,firstRow:first.textContent||"",count:drafts.length}}await sleep(100)}throw Error("home never returned after browser reload")})()',awaitPromise:true,returnByValue:true});
      if(persisted.exceptionDetails)throw Error('Reload validation failed: '+persisted.exceptionDetails.text);
      const record=persisted.result?.value;
      assert.ok(record?.title&&record.firstRow.includes(record.title),'new draft not restored as first row after real browser reload');
      console.log('PASS draft browser reload · '+record.title+' persisted, first row after refresh');
      const creator=await send('Runtime.evaluate',{expression:'(async()=>{const sleep=ms=>new Promise(r=>setTimeout(r,ms));const drafts=JSON.parse(localStorage.getItem("storyos_local_story_drafts_v1")||"[]");const expected=drafts[drafts.length-1]?.id;const selected=localStorage.getItem("storyos_active_local_story_id_v1");if(!expected||selected!==expected)throw Error("most recently selected local draft identity was lost on reload");const nav=document.querySelector("nav[aria-label=主要页面]");const button=[...nav.querySelectorAll("button")].find(b=>b.textContent.trim()==="故事制作");if(!button)throw Error("creator navigation missing");button.click();for(let i=0;i<180;i++){const page=document.querySelector("main [aria-label=分镜与素材创作画布]");const header=[...document.querySelectorAll("header button")].find(b=>b.textContent.includes(drafts[drafts.length-1].title));if(page&&header)return {expected,selected,title:drafts[drafts.length-1].title};await sleep(100)}throw Error("restored local draft not visible in creator after reload")})()',awaitPromise:true,returnByValue:true});
      if(creator.exceptionDetails)throw Error('Draft selection restore failed: '+(creator.exceptionDetails.exception?.description||creator.exceptionDetails.text));
      assert.equal(creator.result?.value?.selected,creator.result?.value?.expected,'local draft context should survive browser reload');
      console.log('PASS local draft editor selection survives browser reload · '+creator.result.value.title);

   }
 }finally{if(ws)ws.close();child.kill();}
}
console.log('R32_LOCAL_DRAFT_SORT_1_OF_1_PASS');
