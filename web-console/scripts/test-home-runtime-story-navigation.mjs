import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';

const base=process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/';
const chrome=process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const profile=path.resolve('../.storyos-tmp/ui-qa/story-workbench-route-'+process.pid);
fs.mkdirSync(profile,{recursive:true});
const child=spawn(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
  '--no-first-run','--remote-debugging-port=0','--window-size=1440,900','--user-data-dir='+profile,base],{stdio:'ignore'});
const sleep=(ms)=>new Promise(resolve=>setTimeout(resolve,ms));
let ws;
try {
  let port=0;
  for(let i=0;i<220;i++){
    const file=path.join(profile,'DevToolsActivePort');
    if(fs.existsSync(file)){port=Number(fs.readFileSync(file,'utf8').split('\n')[0]);if(port>0)break;}
    await sleep(100);
  }
  assert.ok(port,'Chrome CDP port missing');
  let target;
  for(let i=0;i<180;i++){
    try{target=(await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json())).find(x=>x.type==='page'&&x.url.startsWith(base));if(target)break;}catch{}
    await sleep(100);
  }
  assert.ok(target?.webSocketDebuggerUrl,'Chrome page missing');
  ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
  let seq=0;const pending=new Map();
  ws.addEventListener('message',event=>{
    let value;try{value=JSON.parse(event.data);}catch{return;}
    if(!pending.has(value.id))return;
    const handler=pending.get(value.id);pending.delete(value.id);
    value.error?handler.reject(Error(value.error.message)):handler.resolve(value.result);
  });
  const send=(method,params={})=>new Promise((resolve,reject)=>{
    const id=++seq;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));
  });
  await send('Runtime.enable');await send('Page.enable');await sleep(1200);
  const expression='(async()=>{const nap=ms=>new Promise(r=>setTimeout(r,ms));for(let i=0;i<150;i++){const gallery=document.querySelector("[aria-label=\\"最近创作画廊\\"]");const card=gallery?.querySelector("button[aria-label^=\\"打开最近创作 深渊疗愈所\\"]");if(card){card.click();break;}await nap(150);}for(let i=0;i<150;i++){const view=document.querySelector("#storyos-runtime-story-workbench");const title=view?.querySelector("h2")?.textContent||"";const pic=view?.querySelector(\'img[alt*="未经审核"]\');if(view&&title.includes("深渊疗愈所")&&pic?.complete&&pic.naturalWidth>0){const header=document.querySelector("header")?.textContent||"";return {ok:true,title,header,ref:view.getAttribute("data-episode-ref"),story:!!view.querySelector("[aria-label=\\"故事内容\\"]"),candidate:pic.naturalWidth>0,monitorButton:[...view.querySelectorAll("button")].some(x=>x.textContent.includes("生产监控"))};}await nap(150);}return {ok:false,body:document.body.textContent.slice(0,380)}})()';
  let answer;
  for(let i=0;i<7;i++){
    try{
      const result=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
      if(result.exceptionDetails)throw Error(result.exceptionDetails.text);
      answer=result.result?.value;break;
    }catch(error){if(i===6||!String(error).includes('Execution context was destroyed'))throw error;await sleep(400);}
  }
  assert.ok(answer?.ok&&answer.story&&answer.candidate&&answer.monitorButton&&answer.header.includes('深渊疗愈所'),JSON.stringify(answer));
  console.log('PASS HOME_RUNTIME_STORY_DETAIL '+answer.ref+' '+answer.title);
} finally {if(ws)ws.close();child.kill();}
