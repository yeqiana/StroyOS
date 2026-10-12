import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';

const dist=path.resolve('dist');
const html=fs.readFileSync(path.join(dist,'index.html'),'utf8');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome));
const server=spawn(process.execPath,['scripts/test-static-server.mjs',dist],{stdio:['ignore','pipe','pipe']});
const port=await new Promise((resolve,reject)=>{
  let raw='';const timeout=setTimeout(()=>reject(new Error('HTTP server startup timeout')),12000);
  server.stdout.on('data',x=>{raw+=x.toString();const found=raw.match(/READY (\d+)/);if(found){clearTimeout(timeout);resolve(Number(found[1]));}});
  server.once('error',reject);
});
const mock=[
  'window.__page2Calls=0;',
  'window.fetch=async input=>{',
  'const request=new URL(String(input),"http://localhost");',
  'if(!request.pathname.includes("/api/v1/runtime/statuses"))throw Error("fixture blocks non-read HTTP call");',
  'const offset=Number(request.searchParams.get("offset")||0);',
  'const limit=Number(request.searchParams.get("limit")||100);',
  'if(offset===100)window.__page2Calls++;',
  'const items=Array.from({length:101},(_,i)=>({schema_version:1,projection_level:"summary",episode_id:"fixture-"+i,episode_ref:"R7_"+i,title:"监控阶段作品 "+i,production_stage:"STORYBOARD_LOCKED",state_source:"fixture"}));',
  'const page=items.slice(offset,offset+limit);',
  'return new Response(JSON.stringify({code:"OK",data:{items:page,count:page.length,total:101,limit,offset,has_more:offset+page.length<items.length,stage_counts:{},errors:[]}}),{status:200,headers:{"Content-Type":"application/json"}});',
  '};'
].join('\n');
const js=[
 '(async()=>{try{',
 'const wait=ms=>new Promise(r=>setTimeout(r,ms));',
 'let nav;',
 'for(let i=0;i<100&&!nav;i++){nav=[...document.querySelectorAll("nav button")].find(b=>b.textContent.trim()==="生产监控");if(!nav)await wait(100);}',
 'if(!nav)throw Error("navigation");nav.click();',
 'let loaded=false;',
 'for(let i=0;i<150;i++){if((document.querySelector("main")?.textContent||"").includes("已读 100 / 101")){loaded=true;break;}await wait(100);}',
 'if(!loaded)throw Error("first page not read");',
 'const next=[...document.querySelectorAll("main button")].find(b=>b.textContent.trim()==="从 Platform API 加载下一页");',
 'if(!next)throw Error("no next page action");next.click();next.click();',
 'let complete=false;',
 'for(let i=0;i<150;i++){if((document.querySelector("main")?.textContent||"").includes("已读 101 / 101")){complete=true;break;}await wait(100);}',
 'if(!complete)throw Error("last page not appended");',
 'if(window.__page2Calls!==1)throw Error("duplicate page request "+window.__page2Calls);',
 'document.body.dataset.monitorPages="pass";',
 '}catch(e){document.body.dataset.monitorPages="fail:"+e.message}})();'
].join('\n');
const entry='qa-r7-monitor-pages.html';
fs.writeFileSync(path.join(dist,entry),html.replace('</head>','<script>'+mock+'</script></head>').replace('</body>','<script>'+js+'</script></body>'));
const report=path.resolve('../.storyos-tmp/ui-qa');fs.mkdirSync(report,{recursive:true});
try {
  const result=spawnSync(chrome,[
    '--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage',
    '--virtual-time-budget=26000','--window-size=1440,900',
    '--user-data-dir='+path.join(report,'r7-monitor-pages'),
    '--dump-dom','http://127.0.0.1:'+port+'/'+entry
  ],{encoding:'utf8',timeout:50000,maxBuffer:5000000});
  const mark=result.stdout?.match(/data-monitor-pages="([^"]+)"/)?.[1]||'missing';
  if(mark!=='pass'){
    fs.writeFileSync(path.join(report,'r7-monitor-pages-debug.txt'),(result.stdout||'').slice(-22000)+'\n'+(result.stderr||'').slice(-2000));
    throw Error('monitor pagination browser test: '+mark);
  }
  console.log('PASS 监控权威阶段 100 → 101 分页且并发双击仅请求一次，历史快照未覆盖');
}finally{server.kill();}
