import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base = new URL(process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','R23 screenshots must use local evidence only');
const chrome = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const reportDir = path.resolve('../.storyos-tmp/ui-qa/r23');
fs.mkdirSync(reportDir,{recursive:true});
const html = fs.readFileSync('index.html','utf8');
const cases = [
  {name:'story-review-focus', width:1366, menu:'故事制作'},
  {name:'monitor-authority-filter', width:1280, menu:'生产监控'},
  {name:'workflow-sort-inspector', width:1280, menu:'工作流'},
  {name:'run-frame-status-list', width:1024, menu:'生产监控'},
];
const scriptFor=(c)=>[
  '(async()=>{try{',
  'const c='+JSON.stringify(c)+';const pause=ms=>new Promise(r=>setTimeout(r,ms));',
  'const wait=async(fn,why)=>{for(let i=0;i<250;i++){const x=fn();if(x)return x;await pause(110)}throw Error("timeout "+why)};',
  'const nav=await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"sidebar");',
  'const menu=[...nav.querySelectorAll("button")].find(el=>el.textContent?.trim()===c.menu);if(!menu)throw Error("no menu "+c.menu);menu.click();',
  'if(c.name==="story-review-focus"){',
  ' const heading=await wait(()=>[...document.querySelectorAll("main h3")].find(x=>x.textContent?.trim()==="逐帧审核"),"review heading");',
  ' const section=heading.closest(\'section[aria-label="逐帧审核检视区"]\');if(!section)throw Error("review section missing");',
  ' const count=Number(section.textContent?.match(/需检查\\s*(\\d+)\\s*项/)?.[1]??"NaN");if(!Number.isInteger(count))throw Error("attention count invalid");',
  ' const quick=[...section.querySelectorAll("button")].find(b=>b.textContent?.includes("只看待查"));',
  ' const toggle=await wait(()=>section.querySelector("button[aria-expanded]"),"review toggle");toggle.click();',
  ' await wait(()=>section.querySelector(".os-console-filterbar .ant-select"),"review dropdown");',
  ' if(toggle.getAttribute("aria-expanded")!=="true")throw Error("reviews not expanded");',
  ' if(!section.textContent.includes("已匹配"))throw Error("review page counter missing");',
  ' if(count){if(!quick)throw Error("attention shortcut missing");quick.click();await wait(()=>section.textContent?.includes("已匹配 "+count+" /"),"attention filter");}',
  ' else if(quick||!section.textContent?.includes("暂无待查记录"))throw Error("zero attention should show summary instead of inert button");',
  '}else if(c.name==="monitor-authority-filter"){',
  ' const section=await wait(()=>document.querySelector(\'[aria-label="只读状态记录及数据来源"]\'),"authority section");',
  ' const selector=await wait(()=>section.querySelector(".os-console-filterbar .ant-select"),"stage select");',
  ' if(!section.textContent.includes("匹配"))throw Error("authority match counter missing");',
  ' const rows=await wait(()=>section.querySelectorAll(".storyos-authority-grid tbody tr.cursor-pointer").length>=3,"authority rows");',
  ' if(!rows)throw Error("authority stage list unavailable");',
  ' const combobox=selector.querySelector("[role=combobox]");if(!combobox||!selector.textContent?.includes("全部阶段"))throw Error("stage filter control invalid");',
  ' const pager=section.querySelector(".ant-pagination");if(!pager)throw Error("authority paging missing");',
  ' const row=await wait(()=>section.querySelector(".storyos-authority-grid tbody tr.cursor-pointer"),"filtered authority row");row.click();',
  ' const detail=await wait(()=>document.querySelector(".storyos-authority-inspector .ant-drawer-body"),"authority drawer");',
  ' await wait(()=>detail.textContent?.includes("数据来源"),"authority detail evidence");',
  ' const close=document.querySelector(".storyos-authority-inspector .ant-drawer-close");if(!close)throw Error("inspector close missing");close.click();',
  ' await wait(()=>!document.querySelector(".storyos-authority-inspector"),"authority drawer closed");',
  '}else if(c.name==="workflow-sort-inspector"){',
  ' const section=await wait(()=>document.querySelector("#storyos-workflow-workspace"),"workflow section");',
  ' const title=await wait(()=>[...section.querySelectorAll(".ant-table-tbody tr td div[title]")].find(x=>x.textContent?.trim()),"workflow record");',
  ' const firstTitle=title.textContent.trim();',
  ' const input=await wait(()=>section.querySelector(\'input[aria-label="搜索已载入作品"]\'),"workflow search");',
  ' const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;setter.call(input,firstTitle);input.dispatchEvent(new Event("input",{bubbles:true}));',
  ' const reset=await wait(()=>section.querySelector(\'button[aria-label="清除工作流筛选"]\'),"workflow reset");',
  ' await wait(()=>section.textContent?.includes("当前匹配 1 条"),"workflow search count");reset.click();',
  ' await wait(()=>section.textContent?.includes("当前匹配 20 条"),"workflow reset result");',
  ' const sorter=await wait(()=>section.querySelector(".ant-table-thead th.ant-table-column-has-sorters"),"sort column");sorter.click();',
  ' await wait(()=>sorter.querySelector(".active")||sorter.getAttribute("aria-sort")&&!sorter.getAttribute("aria-sort").includes("none"),"table sorting");',
  ' const row=await wait(()=>[...section.querySelectorAll(".ant-table-tbody tr")].find(tr=>tr.querySelector("button[aria-label^=\\"查看阶段详情：\\"]")),"sorted data row");row.querySelector("td")?.click();',
  ' const detail=await wait(()=>document.querySelector(".storyos-workflow-inspector .ant-drawer-body"),"workflow inspector");',
  ' await wait(()=>detail.textContent?.includes("阶段摘要"),"workflow evidence summary");',
  '}else if(c.name==="run-frame-status-list"){',
  ' const history=await wait(()=>[...document.querySelectorAll(\'#storyos-production-monitor-view .ant-segmented-item-label\')].find(x=>x.textContent?.includes("历史 Run")),"history view");history.click();',
  ' const row=await wait(()=>document.querySelector(".storyos-monitor-grid tbody tr.cursor-pointer"),"historical run");row.click();',
  ' await wait(()=>document.querySelector("main")?.textContent?.includes("历史工作区 Run 快照"),"run detail");',
  ' const label=await wait(()=>[...document.querySelectorAll("main .ant-segmented-item-label")].find(x=>x.textContent?.trim()==="状态列表"),"frame view switch");label.click();',
  ' const table=await wait(()=>[...document.querySelectorAll("main .ant-table")].find(x=>x.textContent?.includes("分镜标识")&&x.textContent?.includes("尝试")),"frame status table");',
  ' const trs=await wait(()=>[...table.querySelectorAll("tbody tr")].filter(x=>x.querySelector("td")).length>=10,"frame rows");if(!trs)throw Error("frame list empty");',
  ' if(!table.textContent?.includes("PASSED")&&!table.textContent?.includes("RETRYING"))throw Error("frame statuses missing");',
  ' const frameRow=await wait(()=>table.querySelector("tbody tr.cursor-pointer td"),"clickable frame row");frameRow.click();',
  ' const inspector=await wait(()=>document.querySelector(\'[role="dialog"][aria-label="分镜详情检视"]\'),"frame inspector");',
  ' inspector.querySelector(\'button[aria-label="关闭分镜详情"]\')?.click();',
  ' await wait(()=>!document.querySelector(\'[role="dialog"][aria-label="分镜详情检视"]\'),"close inspector");',
  '}',
  'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("document overflow");',
  'document.body.dataset.r23Result="pass";',
  '}catch(e){document.body.dataset.r23Result="fail:"+e.message}})();'
].join('\n');

try{
  for(const c of cases){
    const page='qa-r23-'+c.name+'.html';
    fs.writeFileSync(page,html.replace('</body>','<script>'+scriptFor(c)+'</script></body>'));
    const url=new URL('/'+page,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=36000','--window-size='+c.width+',900','--user-data-dir='+path.join(reportDir,'profile-'+c.name)];
    const check=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:7000000});
    const result=check.stdout?.match(/data-r23-result="([^"]+)"/)?.[1]||'missing';
    if(result!=='pass'){
      fs.writeFileSync(path.join(reportDir,'failure-'+c.name+'.txt'),(check.stdout||'').slice(-16500)+'\n'+(check.stderr||'').slice(-1300));
      throw Error(c.name+' '+result);
    }
    const file=path.join(reportDir,'storyos-r23-'+c.name+'.png');
    const shot=spawnSync(chrome,[...args,'--screenshot='+file,url],{encoding:'utf8',timeout:85000});
    assert.equal(shot.status,0,'Chrome screenshot command failed: '+c.name);
    assert.ok(fs.existsSync(file)&&fs.statSync(file).size>6500,'screenshot not created: '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px, screenshot '+fs.statSync(file).size+' bytes');
  }
  console.log('R23_FOUR_SLOT_REAL_BROWSER_4_OF_4_PASS');
}finally{
  for(const c of cases)try{fs.unlinkSync('qa-r23-'+c.name+'.html')}catch{}
}