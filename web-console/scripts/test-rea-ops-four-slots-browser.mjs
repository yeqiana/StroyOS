import assert from 'node:assert/strict';
import fs from 'node:fs';import path from 'node:path';import os from 'node:os';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3119/');assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';assert.ok(fs.existsSync(chrome));
const html=fs.readFileSync('index.html','utf8');
const component=fs.readFileSync('src/components/views/StoryRunDetailView.tsx','utf8');
assert.ok(!component.includes("selectedFrame.lastError || 'NETWORK_ERROR'")&&!component.includes("selectedFrame.failureStage || 'provider_download'")&&!component.includes("selectedFrame.failedAt || '11:18:22'")&&!component.includes('nextRetryInSeconds || 17'),'No synthetic failure evidence');
for(const kind of ['home','monitor']){
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'rea-ops-'+kind+'-'));
const file='qa-rea-ops-'+kind+'.html';
const scenario=async function(c){
  const wait=async(fn,label)=>{for(let i=0;i<380;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,80));}throw Error('timeout '+label);};
  try{
    const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'navigation');
    const choose=text=>{const b=[...nav.querySelectorAll('button')].find(el=>el.getAttribute('aria-label')===text||el.textContent?.trim()===text);if(!b)throw Error('missing menu '+text);b.click();};
    if(c==='home'){
      const home=await wait(()=>document.querySelector('#storyos-home-overview'),'home overview');
      const summary=await wait(()=>home.querySelector('[aria-label="工作台关注事项与快捷入口"]'),'attention summary');
      if(summary.textContent.includes('部作品有阻塞或失败审核')){
        const anchor=summary.querySelector('a[href="#storyos-attention-episodes"]');
        if(!anchor)throw Error('missing alert index jump');
        const list=await wait(()=>home.querySelector('section[aria-label="多作品待处理索引"]'),'triage index');
        const count=[...list.querySelectorAll('button[aria-label^="检视需关注作品"]')].length;
        if(count===0||count>4)throw Error('invalid triage size '+count);
        if(!list.textContent.includes('非实时队列'))throw Error('missing evidence scope');
        anchor.click();
        if(location.hash!=='#storyos-attention-episodes')throw Error('jump failed');
        const first=list.querySelector('button[aria-label^="检视需关注作品"]');
        first.click();
        await wait(()=>document.querySelector('[aria-label="制作与审核记录"]')||document.querySelector('[aria-label="生产阶段与制作指标"]')||document.querySelector('section[role="status"]'),'episode navigation');
      }
    }else{
      choose('生产监控');
      const switcher=await wait(()=>document.querySelector('[aria-label="生产监控视图"]'),'monitor switch');
      const history=[...switcher.querySelectorAll('label')].find(x=>x.textContent?.includes('历史 Run'));
      if(!history)throw Error('historical run tab absent');
      history.click();
      const row=await wait(()=>document.querySelector('.storyos-monitor-grid table tbody tr[class*="cursor-pointer"]'),'historical run row');
      row.click();
      await wait(()=>document.querySelector('main')?.textContent.includes('历史工作区 Run 快照'),'historical run detail');
      const filter=await wait(()=>document.querySelector('[aria-label="分镜问题筛选"]'),'frame filter');
      const modes=[...filter.querySelectorAll('label')];
      if(!modes.some(x=>x.textContent?.trim()==='全部')||!modes.some(x=>x.textContent?.includes('异常'))||!modes.some(x=>x.textContent?.includes('未通过')))throw Error('triage modes absent');
      const note=document.querySelector('main')?.textContent||'';
      if(!note.includes('不代表当前在线调度'))throw Error('historical authority notice missing');
      const err=modes.find(x=>x.textContent?.includes('异常'));
      err.click();
      const status=await wait(()=>[...document.querySelectorAll('main span')].find(x=>x.textContent?.includes('帧历史快照 · 不代表实时执行')),'filtered summary');
      const match=status.textContent.match(/当前显示 (\d+) \/ (\d+) 帧/);
      if(!match)throw Error('bad filter summary '+status.textContent);
      const n=Number(match[1]),total=Number(match[2]);
      if(n>total)throw Error('wrong filter counts');
      const matrix=await wait(()=>document.querySelector('button[aria-label="分镜展示方式"]')||document.querySelector('[aria-label="分镜展示方式"]'),'layout toggle');
      if(n===0&&!document.querySelector('p[role="status"]'))throw Error('missing empty state');
      const listToggle=[...matrix.querySelectorAll('label')].find(x=>x.textContent?.includes('状态列表'));
      if(!listToggle)throw Error('list switch absent');listToggle.click();
      const table=await wait(()=>document.querySelector('table[aria-label="历史分镜状态列表"]')||document.querySelector('[aria-label="历史分镜状态列表"]'),'filtered list');
      const rows=[...table.querySelectorAll('tbody tr')].filter(x=>!x.className.includes('placeholder'));
      if(n>0&&!rows.length)throw Error('filtered list missing');
      const pending=modes.find(x=>x.textContent?.trim()==='未通过');
      pending.click();
      await wait(()=>document.querySelector('main')?.textContent.includes('当前显示'),'pending filter');
      modes.find(x=>x.textContent?.trim()==='全部').click();
      await wait(()=>[...document.querySelectorAll('main span')].some(x=>x.textContent?.includes('当前显示 '+total+' / '+total+' 帧')),'filter reset');
    }
    if(document.documentElement.scrollWidth>innerWidth+5)throw Error('horizontal overflow');
    document.body.dataset.reaOpsStatus='pass';
  }catch(e){document.body.dataset.reaOpsStatus='fail:'+(e.message||e);}
};
fs.writeFileSync(file,html.replace('</body>','<script>('+scenario.toString()+')('+JSON.stringify(kind)+');</script></body>'));
try{
 const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--window-size=1366,900','--virtual-time-budget=43000','--user-data-dir='+profile,'--dump-dom',new URL('/'+file,base).href],{encoding:'utf8',timeout:112000,maxBuffer:9000000});
 const status=r.stdout?.match(/data-rea-ops-status="([^"]+)"/)?.[1]||'missing';
 assert.equal(status,'pass',kind+': '+status+' '+(r.stderr||'').slice(-200));
 console.log('PASS '+kind+' UI triage real Chrome');
}finally{try{fs.unlinkSync(file)}catch{}try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
}
console.log('REA_OPS_FOUR_SLOTS_BROWSER_2_OF_2_PASS');
