import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/';
const address=new URL(base);
assert.equal(address.protocol,'http:');
assert.ok(['127.0.0.1','localhost'].includes(address.hostname),'仅本机允许读取真实工作区证据');
const chrome=process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
assert.ok(fs.existsSync(chrome));
const response=await fetch(new URL('/api/v1/runtime/statuses?limit=100&offset=0',address));
assert.equal(response.status,200);
const payload=await response.json();
assert.equal(payload.code,'OK');
assert.ok(payload.data.total>0,'应读取至少一个真实 episode-state.json');
assert.ok(payload.data.items.every(row=>row.state_source==='local_workspace_episode_state_file'));
assert.equal(new Set(payload.data.items.map(x=>x.episode_ref)).size,payload.data.items.length,'跨作品重复业务 ID 不应冲突');
const title=payload.data.items[0].title;
const detail=await fetch(new URL('/api/v1/runtime/status?episode='+encodeURIComponent(payload.data.items[0].episode_ref),address));
assert.equal(detail.status,200);
const detailData=await detail.json();
assert.equal(detailData.data.execution_status,'UNKNOWN','文件状态不能冒充在线运行');
assert.equal(detailData.data.heartbeat.health,'unknown');
const main=path.resolve('index.html');
const html=fs.readFileSync(main,'utf8');
const qa=path.resolve('qa-r9-real-browser.html');
const js=[
  '(async()=>{try{',
  'const wait=ms=>new Promise(r=>setTimeout(r,ms));',
  'let banner;',
  'for(let i=0;i<150&&!banner;i++){banner=document.querySelector(\'[data-testid="local-real-evidence-banner"]\');if(!banner)await wait(100);}',
  'if(!banner||!banner.textContent.includes("本机文件")||!banner.title.includes("真实作品状态文件"))throw Error("source banner");',
  'let first=false;',
  'for(let i=0;i<200&&!first;i++){first=(document.querySelector("main")?.textContent||"").includes('+JSON.stringify(title)+');if(!first)await wait(100);}',
  'if(!first)throw Error("actual local title not rendered");',
  'let button;',
  'for(let i=0;i<100&&!button;i++){button=[...document.querySelectorAll(\'nav[aria-label="主要页面"] button\')].find(b=>b.textContent.trim()==="生产监控");if(!button)await wait(100);}',
  'if(!button)throw Error("monitor navigation");button.click();',
  'let label=false;',
  'for(let i=0;i<200&&!label;i++){label=(document.querySelector("main")?.textContent||"").includes("本机真实作品状态文件");if(!label)await wait(100);}',
  'if(!label)throw Error("monitor source not labeled");',
  'document.body.dataset.realE2e="pass";',
  '}catch(e){document.body.dataset.realE2e="fail:"+e.message}})();'
].join('\n');
fs.writeFileSync(qa,html.replace('</body>','<script>'+js+'</script></body>'));
const reports=path.resolve('../.storyos-tmp/ui-qa');fs.mkdirSync(reports,{recursive:true});
try{
  const result=spawnSync(chrome,[
    '--headless=new','--disable-gpu','--no-sandbox','--disable-dev-shm-usage',
    '--virtual-time-budget=30000','--window-size=1440,900',
    '--user-data-dir='+path.join(reports,'r9-real-live-browser'),
    '--dump-dom',new URL('/qa-r9-real-browser.html',address).href
  ],{encoding:'utf8',timeout:60000,maxBuffer:4800000});
  const mark=result.stdout?.match(/data-real-e2e="([^"]+)"/)?.[1]||'missing';
  if(mark!=='pass'){
    fs.writeFileSync(path.join(reports,'r9-real-live-failure.txt'),(result.stdout||'').slice(-20000)+'\n'+(result.stderr||'').slice(-1500));
    throw Error('Local actual-data browser E2E: '+mark);
  }
  console.log('PASS 本机真实工作区状态 '+payload.data.total+' 条，浏览器首页/监控/来源、未知心跳状态均验证通过');
}finally{try{fs.unlinkSync(qa)}catch{}}
