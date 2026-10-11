import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';

/** Capture the SAME verified Chrome tab rather than starting a second premature screenshot run. */
const base='http://127.0.0.1:3100/';
const dir=path.resolve('../.storyos-tmp/ui-qa/r26');
fs.mkdirSync(dir,{recursive:true});
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const catalog=await fetch(base+'api/v1/local-media/catalog').then(response=>response.json());
assert.equal(catalog.data?.source,'local_workspace_approved_only');
const media=catalog.data.items.find(item=>item.frames?.length>=10);
assert.ok(media?.title,'capture requires an episode with real approved frames');
const source=fs.readFileSync('scripts/test-r26-creator-browser.mjs','utf8');
const fragment=source.split('async function scenario(c){')[1]?.split('\n}\n\ntry{')[0];
assert.ok(fragment,'R26 browser scenario not found');
const fn='async function scenario(c){'+fragment+'\n}';
const index=fs.readFileSync('index.html','utf8');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));

for(const width of [1440,1024]){
  const temporaryPage='qa-r26-cdp-'+width+'.html';
  const url=base+temporaryPage;
  const scenario={name:'creator-dual-compare-'+width,width,kind:'compare',title:media.title};
  fs.writeFileSync(temporaryPage,index.replace('</body>','<script>('+fn+')('+JSON.stringify(scenario)+');</script></body>'));
  // A unique temporary profile avoids stale DevToolsActivePort from prior screenshot runs.
  const profile=path.join(dir,'cdp-verified-'+width+'-'+process.pid);
  const child=spawn(chrome,[
    '--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    '--remote-debugging-port=0','--window-size='+width+',900','--user-data-dir='+profile,url
  ],{stdio:'ignore'});
  let ws;
  try {
    const file=path.join(profile,'DevToolsActivePort');
    let port=null;
    for(let i=0;i<180;i++){if(fs.existsSync(file)){port=Number(fs.readFileSync(file,'utf8').split('\n')[0]);break;}await sleep(100);}
    assert.ok(port,'Chrome debugging port not found');
    let target;
    for(let i=0;i<180;i++){
      try{target=(await fetch('http://127.0.0.1:'+port+'/json/list').then(r=>r.json()))
        .find(item=>item.type==='page'&&item.url.includes(temporaryPage));if(target)break;}catch{}
      await sleep(100);
    }
    assert.ok(target?.webSocketDebuggerUrl,'verified tab not found');
    ws=new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{
      ws.addEventListener('open',resolve,{once:true});
      ws.addEventListener('error',reject,{once:true});
    });
    const pending=new Map();let nextId=0;
    ws.addEventListener('message',event=>{
      let message;try{message=JSON.parse(event.data);}catch{return;}
      if(!message.id||!pending.has(message.id))return;
      const request=pending.get(message.id);pending.delete(message.id);
      message.error?request.reject(Error(message.error.message)):request.resolve(message.result);
    });
    const send=(method,params={})=>new Promise((resolve,reject)=>{
      const id=++nextId;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));
    });
    await send('Runtime.enable');await send('Page.enable');
    let status='';
    for(let i=0;i<350;i++){
      const response=await send('Runtime.evaluate',{
        expression:'document.body?.dataset?.r26Result || ""',returnByValue:true
      });
      status=response.result?.value||'';
      if(status==='pass'||status.startsWith('fail:'))break;
      await sleep(100);
    }
    assert.equal(status,'pass','Chrome screenshot only after verified scenario');
    await sleep(650);
    const checked=await send('Runtime.evaluate',{
      expression:'Array.from(document.querySelectorAll(\'[aria-label="双帧素材对照"] img\')).length===2 && Array.from(document.querySelectorAll(\'[aria-label="双帧素材对照"] img\')).every(img=>img.complete&&img.naturalWidth>0)',returnByValue:true
    });
    assert.equal(checked.result?.value,true,'both real images must be visible and decoded');
    const screenshot=await send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false});
    const targetFile=path.join(dir,'storyos-r26-cdp-compare-'+width+'.png');
    fs.writeFileSync(targetFile,Buffer.from(screenshot.data,'base64'));
    assert.ok(fs.statSync(targetFile).size>10000);
    console.log('PASS verified comparison screenshot '+width+'px · '+fs.statSync(targetFile).size+' bytes');
  } finally {
    if(ws)ws.close();
    child.kill();
    try{fs.unlinkSync(temporaryPage);}catch{}
  }
}
console.log('R26_CDP_SAME_VERIFIED_BROWSER_SCREENSHOTS_2_OF_2_PASS');
