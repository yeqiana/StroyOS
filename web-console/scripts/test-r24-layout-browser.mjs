import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base = new URL(process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','Only local read-only evidence is acceptable');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r24');
fs.mkdirSync(dir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[
  {name:'workbench-dual-column',width:1366,menu:'故事制作'},
  {name:'monitor-primary-stages',width:1366,menu:'生产监控'},
  {name:'monitor-history-switch',width:1366,menu:'生产监控'},
  {name:'workflow-full-list',width:1280,menu:'工作流'},
  {name:'run-auto-list',width:1024,menu:'生产监控'}
];

function browserScript(c) {
  return [
    '(async()=>{try{',
    'const c='+JSON.stringify(c)+';',
    'const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
    'const wait=async(fn,label)=>{for(let i=0;i<260;i++){const x=fn();if(x)return x;await sleep(90)}throw Error("timeout "+label)};',
    'const nav=await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"navigation");',
    'const target=[...nav.querySelectorAll("button")].find(b=>b.textContent?.trim()===c.menu);if(!target)throw Error("menu "+c.menu);target.click();',
    'if(c.name==="workbench-dual-column"){',
    ' const grid=await wait(()=>document.querySelector(\'[aria-label="当前批次与审核双栏工作区"]\'),"workbench split");',
    ' const batch=grid.querySelector("section");const review=grid.querySelector(\'section[aria-label="逐帧审核检视区"]\');',
    ' if(!batch||!review)throw Error("workbench section missing");',
    ' const cols=getComputedStyle(grid).gridTemplateColumns.split(" ").filter(Boolean);if(cols.length!==2)throw Error("workbench not two-column: "+cols.join("/"));',
    ' const a=batch.getBoundingClientRect(),b=review.getBoundingClientRect();if(Math.abs(a.top-b.top)>5)throw Error("workbench panels are stacked");',
    ' if(a.width<b.width)throw Error("batch is not primary column");',
    ' if(document.querySelectorAll("main .os-console-toolbar").length<1)throw Error("workbench toolbar absent");',
    '}else if(c.name==="monitor-primary-stages"){',
    ' const section=await wait(()=>document.querySelector(\'[aria-label="阶段证据主视图"]\'),"stage workspace");',
    ' const nav=document.querySelector(\'[aria-label="生产监控主工作区切换"]\');',
    ' if(!nav||!nav.textContent.includes("阶段证据")||!nav.textContent.includes("历史 Run"))throw Error("master-detail tabs missing");',
    ' await wait(()=>section.querySelectorAll(".storyos-authority-grid tbody tr.cursor-pointer").length>=10,"tall data grid");',
    ' if(document.querySelector(\'.storyos-monitor-grid\'))throw Error("history table stacked below primary grid");',
    ' if(!section.textContent.includes("只读"))throw Error("source provenance missing");',
    '}else if(c.name==="monitor-history-switch"){',
    ' const view=await wait(()=>document.querySelector("#storyos-production-monitor-view"),"monitor");',
    ' const tab=await wait(()=>[...view.querySelectorAll(".ant-segmented-item-label")].find(e=>e.textContent?.includes("历史 Run")),"historical tab");tab.click();',
    ' const table=await wait(()=>view.querySelector(".storyos-monitor-grid"),"history run table");',
    ' const rows=await wait(()=>table.querySelectorAll("tbody tr.cursor-pointer").length>=5,"history rows");if(!rows)throw Error("missing runs");',
    ' if(view.querySelector(".storyos-authority-grid"))throw Error("runtime and history views stacked");',
    ' if(!view.textContent.includes("历史工作区运行快照"))throw Error("historical-only banner missing");',
    ' const filters=view.querySelector(".os-console-filterbar .ant-checkbox-wrapper");if(!filters)throw Error("history filters missing");',
    '}else if(c.name==="workflow-full-list"){',
    ' const view=await wait(()=>document.querySelector("#storyos-workflow-workspace"),"workflow");',
    ' const table=await wait(()=>view.querySelector(".ant-table-tbody"),"workflow table");',
    ' await wait(()=>table.querySelectorAll(\'tr:not(.ant-table-placeholder):not(.ant-table-measure-row)\').length>=20,"full loaded workflow list");',
    ' if(!view.textContent.includes("当前匹配 20 条"))throw Error("workflow data count");',
    ' if(view.querySelector("details")?.open)throw Error("reference flow must be collapsed");',
    ' const row=table.querySelector("tr.cursor-pointer");row?.click();',
    ' const drawer=await wait(()=>document.querySelector(".storyos-workflow-inspector .ant-drawer-body"),"workflow inspector");',
    ' if(!drawer.textContent.includes("阶段摘要"))throw Error("inspector lacks summary");',
    ' const close=document.querySelector(".storyos-workflow-inspector .ant-drawer-close");if(!close)throw Error("inspector close missing");close.click();',
    ' await wait(()=>!document.querySelector(".storyos-workflow-inspector"),"drawer closed");',
    '}else if(c.name==="run-auto-list"){',
    ' const view=await wait(()=>document.querySelector("#storyos-production-monitor-view"),"monitor");',
    ' const history=await wait(()=>[...view.querySelectorAll(".ant-segmented-item-label")].find(e=>e.textContent?.includes("历史 Run")),"history tab");history.click();',
    ' const row=await wait(()=>view.querySelector(".storyos-monitor-grid tbody tr.cursor-pointer"),"run");row.click();',
    ' await wait(()=>document.querySelector("main")?.textContent?.includes("历史工作区 Run 快照"),"run detail");',
    ' const selected=await wait(()=>[...document.querySelectorAll("main .ant-segmented-item")].find(x=>x.textContent?.trim()==="状态列表"),"list mode");',
    ' if(!selected.classList.contains("ant-segmented-item-selected"))throw Error("no-preview Run should default to status list");',
    ' const table=await wait(()=>[...document.querySelectorAll("main .ant-table")].find(e=>e.textContent?.includes("分镜标识")),"frame table");',
    ' if(table.querySelectorAll("tbody tr.cursor-pointer").length<10)throw Error("less than ten frames per page");',
    ' const switcher=[...document.querySelectorAll("main .ant-segmented-item-label")].find(e=>e.textContent?.trim()==="缩略矩阵");if(!switcher)throw Error("legacy grid access missing");',
    '}',
    'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("viewport horizontal overflow");',
    'document.body.dataset.r24Result="pass";',
    '}catch(error){document.body.dataset.r24Result="fail:"+error.message}})();'
  ].join('\n');
}

try{
  for(const c of cases){
    const page='qa-r24-'+c.name+'.html';
    fs.writeFileSync(page,html.replace('</body>','<script>'+browserScript(c)+'</script></body>'));
    const url=new URL('/'+page,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=33000','--window-size='+c.width+',900','--user-data-dir='+path.join(dir,'profile-'+c.name)];
    const dom=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:6500000});
    const state=dom.stdout?.match(/data-r24-result="([^"]+)"/)?.[1]||'missing';
    if(state!=='pass'){
      fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(dom.stdout||'').slice(-18000)+'\n'+(dom.stderr||'').slice(-1000));
      throw Error(c.name+' '+state);
    }
    const shot=path.join(dir,'storyos-r24-'+c.name+'.png');
    const screenshot=spawnSync(chrome,[...args,'--screenshot='+shot,url],{encoding:'utf8',timeout:85000});
    assert.equal(screenshot.status,0,'Chrome screenshot failed: '+c.name);
    assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>7000,'screenshot missing: '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px, real Chrome screenshot '+fs.statSync(shot).size+' bytes');
  }
  console.log('R24_REPLANNED_LAYOUT_5_OF_5_PASS');
}finally{
  for(const c of cases)try{fs.unlinkSync('qa-r24-'+c.name+'.html')}catch{}
}