import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base = new URL(process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/');
assert.equal(base.hostname, '127.0.0.1');
const chrome = process.env.CHROME_PATH || 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html = fs.readFileSync('index.html', 'utf8');
const reports = path.resolve('../.storyos-tmp/ui-qa/r20');
fs.mkdirSync(reports, {recursive: true});
const cases = [
  {name:'workbench-reviews', width:1366, menu:'故事制作'},
  {name:'run-detail-inspector', width:1024, menu:'生产监控'},
  {name:'audit-logs', width:1280, menu:'审计日志'}
];
try {
  for (const c of cases) {
    const script = [
      '(async()=>{try{',
      'const c='+JSON.stringify(c)+';',
      'const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
      'const wait=async(fn,why)=>{for(let i=0;i<200;i++){let value=fn();if(value)return value;await sleep(100)}throw Error("timeout "+why)};',
      'const nav=await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"nav");',
      'const link=[...nav.querySelectorAll("button")].find(b=>b.textContent?.trim()===c.menu);if(!link)throw Error("menu "+c.menu);link.click();',
      'if(c.name==="workbench-reviews"){',
      ' await wait(()=>document.querySelector("main")?.textContent?.includes("制作与审核记录"),"workbench");',
      ' const h=[...document.querySelectorAll("main h3")].find(e=>e.textContent?.includes("逐帧审核"));if(!h)throw Error("review heading");',
      ' const section=h.closest(\'section[aria-label="逐帧审核检视区"]\');if(!section)throw Error("review section");',
      ' const toggle=section.querySelector("button[aria-expanded]");if(!toggle)throw Error("review toggle");toggle.click();',
      ' await wait(()=>section.querySelector(".os-console-filterbar .ant-select"),"review native filter");',
      ' if(toggle.getAttribute("aria-expanded")!=="true")throw Error("review not expanded");',
      ' if(!section.textContent.includes("已匹配"))throw Error("review result count missing");',
      '}else if(c.name==="run-detail-inspector"){',
      ' const history=await wait(()=>[...document.querySelectorAll(\'#storyos-production-monitor-view .ant-segmented-item-label\')].find(x=>x.textContent?.includes("历史 Run")),"history view");history.click();',
      ' const row=await wait(()=>document.querySelector(\'.storyos-monitor-grid table tbody tr[class*="cursor-pointer"]\'),"run history row");row.click();',
      ' await wait(()=>document.querySelector("main")?.textContent?.includes("历史工作区 Run 快照"),"run detail");',
      ' const logTab=[...document.querySelectorAll("main button")].find(b=>b.textContent?.trim()==="日志");if(!logTab)throw Error("run log tab");logTab.click();',
      ' await wait(()=>document.querySelector("main .os-console-filterbar .ant-select"),"run log filter");',
      ' const overview=[...document.querySelectorAll("main button")].find(b=>b.textContent?.trim()==="概览");if(!overview)throw Error("overview tab");overview.click();',
      ' const matrix=await wait(()=>[...document.querySelectorAll("main .ant-segmented-item-label")].find(x=>x.textContent?.trim()==="缩略矩阵"),"grid option");matrix.click();',
      ' const grid=await wait(()=>[...document.querySelectorAll("main .grid")].find(e=>e.className.includes("grid-cols-")&&e.querySelectorAll(":scope > button").length>=10),"frame grid");',
      ' grid.querySelector("button").click();',
      ' const inspector=await wait(()=>document.querySelector(\'[role="dialog"][aria-label="分镜详情检视"]\'),"frame inspector");',
      ' if(inspector.getBoundingClientRect().width>innerWidth+1)throw Error("inspector overflows");',
      ' inspector.querySelector(\'button[aria-label="关闭分镜详情"]\').click();',
      ' await wait(()=>!document.querySelector(\'[role="dialog"][aria-label="分镜详情检视"]\'),"close frame inspector");',
      '}else{',
      ' const logs=await wait(()=>document.querySelector("#runtime-logs-view"),"logs");',
      ' await wait(()=>logs.querySelector(".os-console-filterbar .ant-select"),"antd module select");',
      ' if(!logs.textContent.includes("本次最多读取 100 条"))throw Error("loaded data scope missing");',
      ' await wait(()=>logs.textContent.includes("无法读取审计事件"),"readonly events error");',
      '}',
      'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("document horizontal overflow");',
      'document.body.dataset.r20Result="pass";',
      '}catch(e){document.body.dataset.r20Result="fail:"+e.message}})();'
    ].join('\n');
    const filename='qa-r20-'+c.name+'.html';
    fs.writeFileSync(filename, html.replace('</body>', '<script>'+script+'</script></body>'));
    const url = new URL('/'+filename,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=32000','--window-size='+c.width+',900','--user-data-dir='+path.join(reports,'profile-'+c.name)];
    const dom=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:7000000});
    const result=dom.stdout?.match(/data-r20-result="([^"]+)"/)?.[1] || 'missing';
    if(result!=='pass'){
      fs.writeFileSync(path.join(reports,'failure-'+c.name+'.txt'),(dom.stdout||'').slice(-16000)+'\n'+(dom.stderr||'').slice(-1000));
      throw Error(c.name+' '+result);
    }
    const image=path.join(reports,'storyos-'+c.name+'.png');
    spawnSync(chrome,[...args,'--screenshot='+image,url],{encoding:'utf8',timeout:85000});
    assert.ok(fs.existsSync(image)&&fs.statSync(image).size>5000,'screenshot missing '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px, interaction & layout; screenshot '+fs.statSync(image).size+' B');
  }
  console.log('R20_FOUR_SLOTS_LAYOUT_INTERACTION_3_OF_3_PASS');
} finally { for(const c of cases)try{fs.unlinkSync('qa-r20-'+c.name+'.html')}catch{} }
