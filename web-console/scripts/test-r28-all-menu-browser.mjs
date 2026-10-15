import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';

const root=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(root.hostname,'127.0.0.1','R28 must inspect the actual local read-only console');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r28');
fs.mkdirSync(dir,{recursive:true});
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const cases=[
 {name:'overview',menu:'工作台',selector:'#storyos-home-overview',heading:'工作台'},
 {name:'library',menu:'作品与项目',selector:'#series-library-view',heading:'作品与项目'},
 {name:'monitor',menu:'生产监控',selector:'#storyos-production-monitor-view',heading:'生产监控'},
 {name:'workflow',menu:'工作流',selector:'#storyos-workflow-workspace',heading:'生产流程'},
 {name:'agents',menu:'Agents',selector:'#storyos-agent-workspace',heading:'Agents'},
 {name:'logs',menu:'审计日志',selector:'#runtime-logs-view',heading:'审计日志'},
 {name:'settings',menu:'系统设置',selector:'#codex-appearance-settings-view',heading:'系统设置'}
];

async function browserCase(c){
 const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
 const wait=async(fn,label)=>{for(let n=0;n<310;n++){const found=fn();if(found)return found;await sleep(85)}throw Error('timeout '+label)};
 const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
 // The four creator pages remain primary; legacy operations live under Advanced.
 let menu;
 if(c.name==='settings'){
   const account=await wait(()=>document.querySelector('button[aria-label="账号菜单"]'),'account button');
   account.click();
   menu=await wait(()=>document.querySelector('[role="menu"] button[aria-label="系统设置（账号菜单）"]'),'account settings');
 }else{
   if(['workflow','agents','logs'].includes(c.name)){
     const advanced=await wait(()=>[...nav.querySelectorAll('button')].find(button=>button.getAttribute('aria-label')==='高级管理'),'advanced menu');
     if(advanced.getAttribute('aria-expanded')!=='true')advanced.click();
     await wait(()=>advanced.getAttribute('aria-expanded')==='true','advanced expanded');
   }
   menu=await wait(()=>[...nav.querySelectorAll('button')].find(button=>button.getAttribute('aria-label')===c.menu),'navigation menu '+c.menu);
 }
 menu.click();
 const view=await wait(()=>document.querySelector(c.selector),'page '+c.name);
 await wait(()=>view.querySelector('h1')?.textContent?.trim()===c.heading,'page heading '+c.heading);
 let evidence='normal';
 if(c.name==='overview'){
   await wait(()=>view.querySelector('.storyos-home-episode-grid .ant-table-tbody tr'),'full-width episode table');
   if(!view.querySelector('[aria-label="项目概况"]'))throw Error('overview status strip absent');
   if(!view.querySelector('[aria-label="工作台关注事项与快捷入口"]'))throw Error('overview secondary controls absent');
   const grid=view.querySelector('.storyos-home-episode-grid');
   if(grid.getBoundingClientRect().width<view.getBoundingClientRect().width*.82)throw Error('overview primary table does not fill page');
   if(!view.querySelector('button[aria-label^="打开故事 "]'))throw Error('episode actions missing');
   const input=view.querySelector('input[aria-label="搜索作品"]');
   if(!input)throw Error('overview search absent');
   evidence='workspace rows';
 }else if(c.name==='library'){
   const gallery=await wait(()=>view.querySelector('[aria-label="作品封面画廊"]'),'approved gallery');
   const card=await wait(()=>gallery.querySelector('button[aria-label^="预览作品"]'),'episode card');
   if(!view.querySelector('[aria-label="作品库概况"]'))throw Error('library overview absent');
   const approve=await wait(()=>view.querySelector('.ant-checkbox-input'),'approved-only native checkbox');
   approve.click();
   await wait(()=>gallery.querySelector('img[src^="/api/v1/local-media/images/"]'),'verified approved images filtered');
   approve.click();
   await wait(()=>gallery.querySelectorAll('button[aria-label^="预览作品"]').length>=5,'all episodes restored');
   await wait(()=>{const images=[...gallery.querySelectorAll('[aria-label="已批准素材作品画廊"] img[src^="/api/v1/local-media/images/"]')];return images.length>=2&&images.every(image=>image.complete&&image.naturalWidth>0)},'real gallery pictures decoded');
   if(document.querySelector('.storyos-episode-preview-inspector'))throw Error('episode detail should remain closed by default');
   if(!card)throw Error('no card');
   evidence='approved-only filter';
 }else if(c.name==='monitor'){
   const navStage=await wait(()=>view.querySelector('[aria-label="生产阶段快速筛选"]'),'stage summary');
   await wait(()=>view.querySelector('.storyos-authority-grid .ant-table-tbody tr'),'stage main table');
   if(!view.querySelector('input[aria-label="搜索生产阶段作品"]'))throw Error('monitor search missing');
   const keys=[...navStage.querySelectorAll('button')];
   if(keys.length<2)throw Error('stage distribution not displayed');
   keys.find(key=>key.getAttribute('aria-pressed')!=='true')?.click();
   await wait(()=>view.querySelector('select[aria-label="筛选权威阶段"]')||view.querySelector('.ant-select'),'filter control preserved');
   keys[0].click();
   evidence='local stage evidence';
 }else if(c.name==='workflow'){
   const navFlow=await wait(()=>view.querySelector('[aria-label="工作流阶段快速筛选"]'),'7 stage ribbon');
   if(navFlow.querySelectorAll('button').length!==8)throw Error('7 stage filter count inconsistent');
   await wait(()=>view.querySelectorAll('[aria-label="工作流主数据列表"] .ant-table-tbody tr').length>=5&&!view.querySelector('.ant-spin-spinning'),'real workflow rows loaded, not spinner placeholder');
   const choice=navFlow.querySelectorAll('button')[1];
   choice.click();
   await wait(()=>choice.getAttribute('aria-pressed')==='true','stage selection');
   navFlow.querySelectorAll('button')[0].click();
   if(view.querySelector('details[aria-label="七阶段流程"]')?.open)throw Error('technical phase steps should be folded');
   evidence='canonical stage list';
 }else if(c.name==='agents'){
   if(!view.querySelector('[aria-label="Agent Registry 与 Memory 双栏工作区"]'))throw Error('dual area missing');
   if(!view.querySelector('input[aria-label="搜索 Agent Registry"]'))throw Error('registry search missing');
   if(!view.querySelector('[aria-label="Memory 经验检索"]'))throw Error('memory search must be usable without extra tabs');
   if(!view.querySelector('.ant-table'))throw Error('registry data grid missing');
   if(!view.textContent?.includes('只读'))throw Error('registry source policy missing');
   evidence='Registry API state';
 }else if(c.name==='logs'){
   await wait(()=>view.querySelector('[aria-label="已加载审计事件统计"]'),'loaded audit status');
   if(!view.querySelector('.ant-segmented'))throw Error('native log level segmented missing');
   if(!view.querySelector('input[aria-label="搜索日志内容"]'))throw Error('log search missing');
   if(!view.querySelector('table'))throw Error('audit table missing');
   const warn=[...view.querySelectorAll('.ant-segmented-item-label')].find(item=>item.textContent?.includes('WARN'));
   warn?.click();
   await wait(()=>view.querySelector('[aria-label="已加载审计事件统计"]'),'segmented ready');
   const all=[...view.querySelectorAll('.ant-segmented-item-label')].find(item=>item.textContent?.includes('ALL'));
   all?.click();
   evidence=view.querySelector('[role="alert"]')?'read-only events endpoint unavailable':'loaded events';
 }else if(c.name==='settings'){
   if(view.querySelectorAll('.ant-tabs').length!==1)throw Error('native settings tabs must remain');
   if(!view.querySelector('[aria-label="外观设置双栏工作区"]'))throw Error('full-width appearance page missing');
   const segmented=view.querySelector('[aria-label="界面主题"]');
   if(!segmented)throw Error('theme selector missing');
   const pipelineTab=await wait(()=>[...view.querySelectorAll('.ant-tabs-tab')].find(tab=>tab.textContent?.includes('生产管线')),'runtime settings tab');
   pipelineTab.click();
   await wait(()=>view.querySelector('[aria-label="生产配置双栏工作区"]'),'runtime policy full width');
   if(!view.textContent?.includes('尚无已授权'))throw Error('unauthorized settings policy missing');
   const appearance=[...view.querySelectorAll('.ant-tabs-tab')].find(tab=>tab.textContent?.includes('外观设置'));
   appearance?.click();
   await wait(()=>view.querySelector('[aria-label="外观设置双栏工作区"]'),'back to appearance');
   evidence='runtime permissions unavailable';
 }
 await sleep(360);
 if(document.documentElement.scrollWidth>innerWidth+4)throw Error('horizontal viewport overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
 const main=document.querySelector('main');
 const actual=view.getBoundingClientRect();
 if(actual.width<Math.min(360,(main?.clientWidth||innerWidth)*.75))throw Error('page is unexpectedly narrow');
 return {name:c.name,heading:c.heading,evidence,width:innerWidth,usedWidth:Math.round(actual.width)};
}

// Start a clean Chrome process for each width: page contexts on Windows can be replaced
// when a previous Chrome profile exits, even when a previous CDP test finished.
const widthArg=process.argv.find(arg=>arg.startsWith('--width='));
if(!widthArg){
 for(const width of [1440,1024]){
   const result=spawnSync(process.execPath,[process.argv[1],'--width='+width],{stdio:'inherit',timeout:240000});
   if(result.status!==0)process.exit(result.status||1);
 }
 console.log('R28_ALL_FIRST_LEVEL_MENU_LAYOUT_14_OF_14_PASS');
 process.exit(0);
}
const requestedWidth=Number(widthArg.slice('--width='.length));
assert.ok([1024,1440].includes(requestedWidth),'supported viewport required');
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
      const filename=path.join(dir,'storyos-r28-'+c.name+'-'+width+'.png');
      fs.writeFileSync(filename,Buffer.from(image.data,'base64'));
      assert.ok(fs.statSync(filename).size>9000,'Screenshot failed '+c.name+' '+width);
      console.log('PASS '+c.name+' '+width+'px · '+result.evidence+' · screenshot '+fs.statSync(filename).size+' bytes');
   }
 }finally{if(ws)ws.close();child.kill();}
}
console.log('R28_ALL_FIRST_LEVEL_MENU_LAYOUT_14_OF_14_PASS');
