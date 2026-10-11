import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';

const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1');
const catalogResponse=await fetch(new URL('/api/v1/local-media/catalog',base));
assert.equal(catalogResponse.status,200);
const catalog=await catalogResponse.json();
assert.equal(catalog.data.source,'local_workspace_approved_only');
assert.ok(catalog.data.items.length>=1);
const dir=path.resolve('../.storyos-tmp/ui-qa/r16');fs.mkdirSync(dir,{recursive:true});
const html=fs.readFileSync('index.html','utf8');
const cases=[
  {name:'library-approved',kind:'library'},
  {name:'workbench-approved',kind:'workbench'},
  {name:'run-approved',kind:'run'},
  {name:'library-unapproved',kind:'negative'}
];
try {
 for(const c of cases){
  const script=[
   '(async()=>{try{',
   'const c='+JSON.stringify(c)+';const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
   'const wait=async(fn,where)=>{for(let i=0;i<210;i++){const v=fn();if(v)return v;await sleep(100)}throw Error("Timed out: "+where)};',
   'const nav=await wait(()=>document.querySelector(\'nav[aria-label="主要页面"]\'),"navigation");',
   'const clickMenu=async(name)=>{const b=await wait(()=>[...nav.querySelectorAll("button")].find(x=>x.textContent?.trim()===name),name);b.click()};',
   'if(c.kind==="library"||c.kind==="negative"||c.kind==="workbench"){',
   'await clickMenu("作品与项目");',
   'const main=await wait(()=>document.querySelector("#series-library-view"),"library");',
   'const list=await wait(()=>[...main.querySelectorAll(".ant-segmented-item-label")].find(el=>el.textContent?.trim()==="列表"),"list view");list.click();',
   'const row=await wait(()=>[...main.querySelectorAll("table tbody tr")].find(tr=>tr.textContent?.includes(c.kind==="negative"?"瓶中世界":"婚礼前夜")),"matching table row");',
   'if(c.kind==="negative"){',
   ' if(row.querySelector(\'img[src*="/api/v1/local-media/images/"]\'))throw Error("unapproved cover leaked");',
   ' const album=[...row.querySelectorAll("button")].find(x=>x.getAttribute("aria-label")?.startsWith("打开故事 ")||x.textContent?.includes("查看"));if(!album)throw Error("no negative story link");album.click();',
   ' await wait(()=>document.querySelector("main")?.textContent?.includes("制作与审核记录"),"negative story view");',
   ' if(document.querySelector(\'main img[src*="/api/v1/local-media/images/"]\'))throw Error("unapproved story image leaked");',
   '}else if(c.kind==="workbench"){',
   ' const b=[...row.querySelectorAll("button")].find(x=>x.getAttribute("aria-label")?.startsWith("打开故事 ")||x.textContent?.includes("查看"));if(!b)throw Error("no story open");b.click();',
   ' await wait(()=>document.querySelector(\'[aria-label="分镜与素材创作画布"] button[aria-label^="检视已批准 Frame"]\'),"approved story canvas");',
   '}',
   '}else{await clickMenu("生产监控");',
   ' const history=await wait(()=>[...document.querySelectorAll(\'#storyos-production-monitor-view .ant-segmented-item-label\')].find(x=>x.textContent?.includes("历史 Run")),"history view");history.click();',
   ' const row=await wait(()=>[...document.querySelectorAll(".storyos-monitor-grid table tbody tr")].find(x=>x.textContent?.includes("婚礼前夜")),"historic run row");row.click();',
   ' await wait(()=>document.querySelector("main")?.textContent?.includes("历史工作区 Run 快照"),"run detail");',
   '}',
   'if(c.kind!=="negative"){',
   ' const img=await wait(()=>[...document.querySelectorAll(\'main img[src*="/api/v1/local-media/images/"]\')].find(x=>x.complete&&x.naturalWidth>0),"decoded real approved image");',
   ' if(!img.src.startsWith(location.origin+"/api/v1/local-media/images/"))throw Error("path leaked");',
   ' const pictureCount=document.querySelectorAll(\'main img[src*="/api/v1/local-media/images/"]\').length;',
   ' document.body.dataset.r16Pictures=String(pictureCount);',
   '}',
   'if(document.documentElement.scrollWidth>innerWidth+4)throw Error("viewport overflow");',
   'document.body.dataset.r16Result="pass";',
   '}catch(e){document.body.dataset.r16Result="fail:"+e.message}})();'
  ].join('\n');
  const filename='qa-r16-'+c.name+'.html';
  fs.writeFileSync(filename,html.replace('</body>','<script>'+script+'</script></body>'));
  const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--hide-scrollbars','--virtual-time-budget=35000','--window-size=1440,900','--user-data-dir='+path.join(dir,'profile-'+c.name)];
  const loc=new URL('/'+filename,base).href;
  const dom=spawnSync(chrome,[...args,'--dump-dom',loc],{encoding:'utf8',timeout:83000,maxBuffer:8000000});
  const outcome=dom.stdout?.match(/data-r16-result="([^"]+)"/)?.[1]||'missing';
  if(outcome!=='pass'){
    fs.writeFileSync(path.join(dir,'failure-'+c.name+'.txt'),(dom.stdout||'').slice(-22000)+'\n'+(dom.stderr||'').slice(-1800));
    throw Error(c.name+' failed '+outcome);
  }
  const pictureCount=dom.stdout?.match(/data-r16-pictures="(\d+)"/)?.[1]||'0';
  const shot=path.join(dir,'storyos-'+c.name+'.png');
  const result=spawnSync(chrome,[...args,'--screenshot='+shot,loc],{encoding:'utf8',timeout:83000});
  assert.ok(fs.existsSync(shot)&&fs.statSync(shot).size>6000, 'Missing screenshot '+result.stderr?.slice(-300));
  console.log('PASS',c.name,'decoded real approved photos=',pictureCount,'screenshot=',fs.statSync(shot).size);
 }
 console.log('R16_MEDIA_APPROVED_CHROME_4/4_PASS');
}finally{
 for(const c of cases)try{fs.unlinkSync('qa-r16-'+c.name+'.html')}catch{}
}
