import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtempSync,mkdirSync,readFileSync,existsSync,writeFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {tmpdir} from 'node:os';
const root=process.env.STORYOS_R17_QA_URL||'http://127.0.0.1:3197/';
const token=process.env.STORYOS_R17_OPERATOR_TOKEN;
assert.ok(token&&token.length>=32,'Test-only operator token required');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const screenshotDir=resolve('../.storyos-tmp/ui-qa/r17');
mkdirSync(screenshotDir,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function openChrome(label){
 const profile=mkdtempSync(join(tmpdir(),'storyos-r17-'+label+'-'));
 const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
 '--remote-debugging-port=0','--window-size=1440,900','--user-data-dir='+profile,root],{stdio:'ignore'});
 const portFile=join(profile,'DevToolsActivePort');
 let port=0;
 for(let i=0;i<150;i++){if(existsSync(portFile)){try{port=Number(readFileSync(portFile,'utf8').split('\n')[0]);if(port>0)break;}catch{}}await sleep(100);}
 assert.ok(port,'Chrome DevTools unavailable');
 let target;
 for(let i=0;i<150;i++){try{target=(await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json())).find(x=>x.type==='page'&&x.url.startsWith(root));if(target)break;}catch{}await sleep(100);}
 assert.ok(target,'R17 Chrome page not found');
 const ws=new WebSocket(target.webSocketDebuggerUrl);
 await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
 let n=0;const pending=new Map();
 ws.addEventListener('message',event=>{let response;try{response=JSON.parse(event.data);}catch{return;}
  if(!pending.has(response.id))return;
  const h=pending.get(response.id);pending.delete(response.id);
  response.error?h.reject(Error(response.error.message)):h.resolve(response.result);
 });
 const send=(method,params={})=>new Promise((resolve,reject)=>{let id=++n;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});
 const evaluate=async(expression)=>{
  const data=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(data.exceptionDetails)throw Error(data.exceptionDetails.exception?.description||data.exceptionDetails.text);
  return data.result?.value;
 };
 await send('Runtime.enable');await send('Page.enable');await sleep(1100);
 return {child,ws,send,evaluate};
}
async function focusVault(){
 const wait=async(fn)=>{for(let i=0;i<180;i++){const value=fn();if(value)return value;await new Promise(r=>setTimeout(r,100));}throw Error('timeout opening vault');};
 const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'));
 const menu=[...nav.querySelectorAll('button')].find(b=>b.textContent?.trim()==='作品与项目');
 if(!menu)throw Error('library navigation missing');
 menu.click();
 const vault=await wait(()=>document.querySelector('section[aria-label="本机草稿备份与迁移准备"]'));
 const input=await wait(()=>vault.querySelector('input[aria-label="隔离测试授权口令"]'));
 input.focus();
 return true;
}
async function doAction(action,confirm,mode){
 const wait=async(fn,label)=>{for(let i=0;i<180;i++){const value=fn();if(value)return value;await new Promise(r=>setTimeout(r,100));}throw Error('timeout '+label);};
 const vault=await wait(()=>document.querySelector('section[aria-label="本机草稿备份与迁移准备"]'),'vault');
 const btn=await wait(()=>[...vault.querySelectorAll('button')].find(b=>b.textContent?.trim()===action&&!b.disabled),'enabled action');
 btn.click();
 const confirmation=await wait(()=>[...document.querySelectorAll('.ant-modal-confirm button')].find(b=>b.textContent?.includes(confirm)),'confirm');
 confirmation.click();
 if(mode==='save')await wait(()=>vault.textContent.includes('已保存测试存档'),'saved receipt');
 else await wait(()=>{try{return JSON.parse(localStorage.getItem('storyos_local_story_drafts_v1')||'[]').some(x=>x.id==='ep-home-r17qa001');}catch{return false;}},'restored into independent browser');
 return {mode,drafts:JSON.parse(localStorage.getItem('storyos_local_story_drafts_v1')||'[]').length};
}
async function browse(label,mode){
 const c=await openChrome(label);
 try{
  if(mode==='save'){
   const draft={id:'ep-home-r17qa001',title:'R17 真实浏览器测试草稿',code:'R17QA',synopsis:'测试存档',
    frameReviews:[],preflightChecks:[],storyboardBeats:[],characters:[],currentStage:'IDEA_LOCK',
    runtimeRequest:{mode:'auto_create'}};
   await c.evaluate('localStorage.setItem("storyos_local_story_drafts_v1",'+JSON.stringify(JSON.stringify([draft]))+')');
   await c.send('Page.reload',{ignoreCache:true});await sleep(1200);
  }
  assert.equal(await c.evaluate('('+focusVault.toString()+')()'),true);
  await c.send('Input.insertText',{text:token});await sleep(450);
  const action=mode==='save'?'保存测试存档':'读取最新测试存档';
  const confirm=mode==='save'?'确认测试存档':'确认恢复到浏览器';
  const value=await c.evaluate('('+doAction.toString()+')('+JSON.stringify(action)+','+JSON.stringify(confirm)+','+JSON.stringify(mode)+')');
  assert.equal(value.mode,mode);
  if(mode==='restore')assert.equal(value.drafts,1);
  const image=await c.send('Page.captureScreenshot',{format:'png',fromSurface:true});
  writeFileSync(join(screenshotDir,'storyos-r17-'+mode+'.png'),Buffer.from(image.data,'base64'));
  console.log('CHROME_PASS',JSON.stringify(value));
 }finally{c.ws.close();c.child.kill();}
}
await browse('producer','save');
await browse('consumer','restore');
console.log('R17_TEST_ONLY_TWO_INDEPENDENT_CHROME_PROFILES_PASS');
