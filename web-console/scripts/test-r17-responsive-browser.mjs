import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const dir=path.resolve('../.storyos-tmp/ui-qa/r17');fs.mkdirSync(dir,{recursive:true});
const cases=[
 {name:'home-1024',menu:'工作台',width:1024,heading:'工作台'},
 {name:'monitor-1024',menu:'生产监控',width:1024,heading:'生产监控'},
 {name:'library-1280',menu:'作品与项目',width:1280,heading:'作品与项目'},
 {name:'workflow-1280',menu:'工作流',width:1280,heading:'生产流程'}
];
try {
 for(const c of cases) {
  const script=[
   '(async()=>{try{',
   'const c='+JSON.stringify(c)+';const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
   'let nav;for(let i=0;i<160&&!nav;i++){nav=document.querySelector(\'nav[aria-label="主要页面"]\');if(!nav)await sleep(100)}',
   'if(!nav)throw Error("No sidebar");const menu=[...nav.querySelectorAll("button")].find(b=>b.textContent?.trim()===c.menu);if(!menu)throw Error("No menu");menu.click();',
   'let main;for(let i=0;i<220;i++){main=document.querySelector("main");if(main?.querySelector("h1")?.textContent?.trim()===c.heading)break;await sleep(100)}',
   'if(main?.querySelector("h1")?.textContent?.trim()!==c.heading)throw Error("Heading not loaded");',
   'for(let i=0;i<100;i++){if(main.querySelector("table,.ant-table,[aria-label=\\\"项目概况\\\"]"))break;await sleep(100)}',
   'if(!main.querySelector("table,.ant-table,[aria-label=\\\"项目概况\\\"]"))throw Error("Primary data not visible");',
   'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("Document horizontal overflow");',
   'if(!main.getBoundingClientRect().width||main.getBoundingClientRect().width>innerWidth)throw Error("Main invalid width");',
   'if(!document.querySelector(\'[data-testid="local-real-evidence-banner"]\'))throw Error("Read-only provenance absent");',
   'document.body.dataset.r17Responsive="pass";',
   '}catch(e){document.body.dataset.r17Responsive="fail:"+e.message}})();'
  ].join('\n');
  const page='qa-r17-'+c.name+'.html';fs.writeFileSync(page,html.replace('</body>','<script>'+script+'</script></body>'));
  const profile=path.join(dir,'profile-'+c.name);
  const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--virtual-time-budget=27000','--window-size='+c.width+',900','--user-data-dir='+profile];
  const target=new URL('/'+page,base).href;
  const result=spawnSync(chrome,[...args,'--dump-dom',target],{encoding:'utf8',timeout:65000,maxBuffer:5500000});
  const mark=result.stdout?.match(/data-r17-responsive="([^"]+)"/)?.[1]||'missing';
  if(mark!=='pass'){fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(result.stdout||'').slice(-19000)+'\n'+(result.stderr||'').slice(-1400));throw Error(c.name+' '+mark);}
  const shot=path.join(dir,'storyos-'+c.name+'.png');
  spawnSync(chrome,[...args,'--screenshot='+shot,target],{encoding:'utf8',timeout:65000});
  assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>9000,'Screenshot failed '+c.name);
  console.log('PASS',c.name, 'real-data page and no overflow');
 }
 console.log('R17_RESPONSIVE_CHROME_4/4_PASS');
}finally{for(const c of cases)try{fs.unlinkSync('qa-r17-'+c.name+'.html')}catch{}}
