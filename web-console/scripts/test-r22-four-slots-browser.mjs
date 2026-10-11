import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','R22 screenshots must use local evidence');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const reports=path.resolve('../.storyos-tmp/ui-qa/r22');
fs.mkdirSync(reports,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[
  {name:'monitor-inspector',width:1366,menu:'生产监控'},
  {name:'workflow-inspector',width:1280,menu:'工作流'},
  {name:'monitor-filters',width:1024,menu:'生产监控'},
  {name:'run-compact-frames',width:1024,menu:'生产监控'}
];
const code=(c)=>[
  '(async()=>{try{',
  'const c='+JSON.stringify(c)+';',
  'const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));',
  'const wait=async(fn,name)=>{for(let i=0;i<260;i++){const x=fn();if(x)return x;await pause(90)}throw Error("timeout "+name)};',
  'const nav=await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"nav");',
  'const button=[...nav.querySelectorAll("button")].find(b=>b.textContent?.trim()===c.menu);if(!button)throw Error("menu "+c.menu);button.click();',
  'if(c.name==="monitor-inspector"){',
  ' const section=await wait(()=>document.querySelector(\'[aria-label="只读状态记录及数据来源"]\'),"real evidence section");',
  ' const row=await wait(()=>section.querySelector(".storyos-authority-grid tbody tr.cursor-pointer"),"authority row");row.click();',
  ' const drawer=await wait(()=>document.querySelector(".storyos-authority-inspector .ant-drawer-body"),"authority drawer");',
  ' await wait(()=>drawer.textContent?.includes("生产阶段")&&drawer.textContent?.includes("数据来源"),"authority summary");',
  ' const wrapper=drawer.closest(".ant-drawer-content-wrapper");if(wrapper&&wrapper.getBoundingClientRect().width>Math.min(440,innerWidth)+3)throw Error("authority drawer too wide");',
  '}else if(c.name==="workflow-inspector"){',
  ' const section=await wait(()=>document.querySelector("#storyos-workflow-workspace"),"workflow workspace");',
  ' const title=await wait(()=>[...section.querySelectorAll(".ant-table-tbody tr td div[title]")].find(el=>el.textContent?.trim()),"loaded workflow row title");',
  ' const keyword=(title.textContent||"").trim();if(!keyword)throw Error("empty workflow row title");',
  ' const input=await wait(()=>section.querySelector(\'input[aria-label="搜索已载入作品"]\'),"workflow search");',
  ' const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value").set;setter.call(input,keyword);input.dispatchEvent(new Event("input",{bubbles:true}));',
  ' await wait(()=>section.querySelectorAll(".ant-table-tbody tr:not(.ant-table-measure-row):not(.ant-table-placeholder)").length>=1,"workflow search results");',
  ' if(!section.textContent.includes("当前匹配"))throw Error("workflow count missing");',
  ' setter.call(input,"");input.dispatchEvent(new Event("input",{bubbles:true}));',
  ' await wait(()=>section.querySelectorAll(".ant-table-tbody tr:not(.ant-table-measure-row):not(.ant-table-placeholder)").length>=10,"workflow restored table");',
  ' const btn=await wait(()=>section.querySelector(\'button[aria-label^="查看阶段详情："]\'),"workflow detail");btn.click();',
  ' const drawer=await wait(()=>document.querySelector(".storyos-workflow-inspector .ant-drawer-body"),"workflow drawer");',
  ' await wait(()=>drawer.textContent?.includes("阶段摘要")&&drawer.textContent?.includes("状态来源"),"workflow summary");',
  ' const wrapper=drawer.closest(".ant-drawer-content-wrapper");if(wrapper&&wrapper.getBoundingClientRect().width>Math.min(440,innerWidth)+3)throw Error("workflow drawer too wide");',
  '}else if(c.name==="monitor-filters"){',
  ' const monitor=await wait(()=>document.querySelector("#storyos-production-monitor-view"),"monitor");',
  ' const toolbar=await wait(()=>monitor.querySelector(".os-console-filterbar .ant-checkbox-wrapper")?.closest(".os-console-filterbar"),"monitor history toolbar");',
  ' if(!toolbar.querySelector(".ant-input-affix-wrapper")||!toolbar.querySelector(".ant-checkbox-wrapper"))throw Error("native filters missing");',
  ' const input=toolbar.querySelector(\'input[aria-label="搜索剧集或任务 ID"]\');if(!input)throw Error("native search missing");',
  ' if(!toolbar.querySelector(".ant-btn"))throw Error("native reset missing");',
  ' const rows=await wait(()=>monitor.querySelector(".storyos-monitor-grid tbody tr"),"history rows");if(!rows)throw Error("no historical rows");',
  '}else if(c.name==="run-compact-frames"){',
  ' const row=await wait(()=>document.querySelector(\'.storyos-monitor-grid tbody tr.cursor-pointer\'),"historical run");row.click();',
  ' await wait(()=>document.querySelector("main")?.textContent?.includes("历史工作区 Run 快照"),"run detail");',
  ' const grid=await wait(()=>[...document.querySelectorAll("main .grid")].find(e=>e.querySelectorAll(":scope > button").length>=10&&e.className.includes("grid-cols-")), "frames");',
  ' const without=[...grid.querySelectorAll(":scope > button")].filter(b=>b.textContent?.includes("无原图"));',
  ' if(without.length&&without.some(b=>b.getBoundingClientRect().height>86))throw Error("unverified preview too tall");',
  ' if(grid.querySelectorAll(":scope > button").length<10)throw Error("frames missing");',
  '}',
  'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("horizontal overflow");',
  'document.body.dataset.r22Result="pass";',
  '}catch(e){document.body.dataset.r22Result="fail:"+e.message}})();'
].join('\n');
try{
  for(const c of cases){
    const source='qa-r22-'+c.name+'.html';
    fs.writeFileSync(source,html.replace('</body>','<script>'+code(c)+'</script></body>'));
    const url=new URL('/'+source,base).href;
    const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars',
      '--virtual-time-budget=33000','--window-size='+c.width+',900',
      '--user-data-dir='+path.join(reports,'profile-'+c.name)];
    const check=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:7000000});
    const result=check.stdout?.match(/data-r22-result="([^"]+)"/)?.[1]||'missing';
    if(result!=='pass'){
      fs.writeFileSync(path.join(reports,'failure-'+c.name+'.txt'),(check.stdout||'').slice(-16000)+'\n'+(check.stderr||'').slice(-1200));
      throw Error(c.name+' '+result);
    }
    const screenshot=path.join(reports,'storyos-r22-'+c.name+'.png');
    const shot=spawnSync(chrome,[...args,'--screenshot='+screenshot,url],{encoding:'utf8',timeout:85000});
    assert.equal(shot.status,0,'chrome screenshot failed for '+c.name);
    assert.ok(fs.existsSync(screenshot)&&fs.statSync(screenshot).size>5000,'screenshot missing '+c.name);
    console.log('PASS '+c.name+' '+c.width+'px; screenshot '+fs.statSync(screenshot).size+'B');
  }
  console.log('R22_REAL_BROWSER_FOUR_SLOTS_4_OF_4_PASS');
}finally{
  for(const c of cases)try{fs.unlinkSync('qa-r22-'+c.name+'.html')}catch{}
}
