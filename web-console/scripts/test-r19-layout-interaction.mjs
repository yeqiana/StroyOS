import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3113/');
assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const dir=path.resolve('../.storyos-tmp/ui-qa/r19');fs.mkdirSync(dir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[{name:'collapsed-projects',width:1024},{name:'home-stage-details',width:1366}];
try{
 for(const c of cases){
 const script=[
 '(async()=>{try{',
 'const name='+JSON.stringify(c.name)+';const pause=ms=>new Promise(r=>setTimeout(r,ms));',
 'const wait=async(fn,label)=>{for(let i=0;i<220;i++){const value=fn();if(value)return value;await pause(90)}throw Error("timeout "+label)};',
 'await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"navigation");',
 'if(name==="collapsed-projects"){',
 'const trigger=await wait(()=>document.querySelector(\'button[aria-label="打开项目快捷面板"]\'),"trigger");',
 'if(getComputedStyle(trigger).display==="none"||trigger.getBoundingClientRect().width<30)throw Error("compact trigger invisible");',
 'trigger.click();',
 'const body=await wait(()=>document.querySelector(".ant-drawer-body")?.textContent?.includes("查看全部作品与项目")?document.querySelector(".ant-drawer-body"):null,"drawer");',
 'const episode=[...body.querySelectorAll("button")].find(b=>b.textContent?.includes("婚礼前夜"));if(!episode)throw Error("approved story missing in project shortcut");',
 'episode.click();',
 'await wait(()=>document.querySelector("main")?.textContent?.includes("制作与审核记录"),"story workbench");',
 'if(document.querySelector(".ant-drawer-body")&&getComputedStyle(document.querySelector(".ant-drawer-content-wrapper")).display!=="none"){await pause(250)}',
 '}else{',
 'const section=await wait(()=>document.querySelector(\'[aria-label="平台生产阶段摘要"]\'),"stage evidence section");',
 'const details=await wait(()=>section.querySelector("details"),"collapsible evidence");',
 'if(details.open)throw Error("stage evidence must start collapsed");',
 'const summary=details.querySelector("summary");if(!summary)throw Error("semantic expand missing");',
 'summary.click();if(!details.open)throw Error("stage expand failed");',
 'const pager=await wait(()=>details.querySelector(".ant-pagination"),"stage pagination");',
 'const next=pager.querySelector(".ant-pagination-next button");if(!next||next.disabled)throw Error("no next page");next.click();',
 'await wait(()=>pager.querySelector(".ant-pagination-item-active")?.textContent?.trim()==="2","stage page 2");',
 'summary.click();if(details.open)throw Error("stage collapse failed");',
 '}',
 'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("viewport horizontal overflow");',
 'document.body.dataset.r19Interaction="pass";',
 '}catch(e){document.body.dataset.r19Interaction="fail:"+e.message}})();'
 ].join('\n');
 const name='qa-r19-'+c.name+'.html';fs.writeFileSync(name,html.replace('</body>','<script>'+script+'</script></body>'));
 const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=32000','--window-size='+c.width+',900','--user-data-dir='+path.join(dir,'profile-'+c.name)];
 const url=new URL('/'+name,base).href;
 const check=spawnSync(chrome,[...args,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:7000000});
 const mark=check.stdout?.match(/data-r19-interaction="([^"]+)"/)?.[1]||'missing';
 if(mark!=='pass'){fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(check.stdout||'').slice(-19000)+'\n'+(check.stderr||'').slice(-1500));throw Error(c.name+' '+mark)}
 const shot=path.join(dir,'storyos-'+c.name+'.png');
 spawnSync(chrome,[...args,'--screenshot='+shot,url],{encoding:'utf8',timeout:85000});
 assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>6000,'No screenshot');
 console.log('PASS '+c.name+' interaction and no horizontal overflow, screenshot '+fs.statSync(shot).size+'B');
 }
 console.log('R19_COMPACT_PROJECTS_AND_HOME_STAGE_2_OF_2_PASS');
}finally{for(const c of cases)try{fs.unlinkSync('qa-r19-'+c.name+'.html')}catch{}}
