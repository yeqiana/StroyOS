import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3120/');assert.equal(base.hostname,'127.0.0.1');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';assert.ok(fs.existsSync(chrome));
const html=fs.readFileSync('index.html','utf8');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-rea-font-'));
try{for(const c of ['save','restore','blocked']){
 const own=c==='blocked'?fs.mkdtempSync(path.join(os.tmpdir(),'storyos-rea-font-blocked-')):profile;
 const name='qa-rea-font-settings-'+c+'.html';
 fs.writeFileSync(name,html.replace('</body>','<script>('+(async function(c){
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const wait=async(fn,label)=>{for(let i=0;i<350;i++){const got=fn();if(got)return got;await sleep(90);}throw Error('timeout '+label)};
  try{
    const settings=await wait(()=>[...document.querySelectorAll('button')].find(b=>b.getAttribute('aria-label')==='系统设置'||b.textContent?.trim()==='系统设置'),'settings menu');
    if(!settings)throw Error('settings menu unavailable');
    settings.click();
    const page=await wait(()=>document.querySelector('#codex-appearance-settings-view'),'settings page');
    const fonts=await wait(()=>page.querySelector('[aria-label="字体偏好"]'),'font segmented');
    const labels=[...fonts.querySelectorAll('label')];
    const balanced=labels.find(l=>l.textContent?.trim()==='均衡显示'),chinese=labels.find(l=>l.textContent?.trim()==='中文优先');
    if(!balanced||!chinese)throw Error('missing font modes');
    const title=page.querySelector('h1.os-page-heading'),section=page.querySelector('h2.os-section-heading');
    const a=getComputedStyle(title),b=getComputedStyle(section);
    if(a.fontSize!=='20px'||a.fontWeight!=='600'||a.lineHeight!=='28px')throw Error('heading hierarchy wrong '+a.fontSize+'/'+a.fontWeight+'/'+a.lineHeight);
    if(b.fontSize!=='14px'||b.fontWeight!=='600'||b.lineHeight!=='20px')throw Error('section hierarchy wrong '+b.fontSize+'/'+b.fontWeight+'/'+b.lineHeight);
    const saved=page.querySelector('[role="status"]');
    const preview=page.querySelector('[aria-label="字体实时预览"]');
    if(!preview?.textContent?.includes('FRAME_08')||!preview.textContent.includes('五十亩山地之后'))throw Error('missing preview evidence');
    const numeric=preview.querySelector('.storyos-font-sample-number');
    if(getComputedStyle(numeric).fontVariantNumeric!=='tabular-nums')throw Error('numbers not tabular');
    if(c==='save'||c==='blocked'){
      if(c==='blocked'){
        const orig=Storage.prototype.setItem;
        Storage.prototype.setItem=function(key,...rest){if(key==='storyos:font-preference:v1')throw Error('storage unavailable');return orig.call(this,key,...rest);};
      }
      chinese.click();
      await wait(()=>document.documentElement.dataset.storyosFont==='chinese','chinese switch');
      const family=getComputedStyle(document.body).fontFamily;
      if(!family.includes('PingFang SC')||family.indexOf('PingFang SC')>family.indexOf('Inter')&&family.includes('Inter'))throw Error('font precedence not Chinese '+family);
      if(c==='save'){
        if(localStorage.getItem('storyos:font-preference:v1')!=='chinese')throw Error('persistence missing');
        if(!saved?.textContent?.includes('已保存到本机浏览器'))throw Error('false save feedback');
      }else if(!saved?.textContent?.includes('仅当前会话生效'))throw Error('blocked storage claimed success');
      if(c==='save'){
        const theme=page.querySelector('[aria-label="界面主题"]');
        const light=[...theme.querySelectorAll('label')].find(l=>l.textContent?.trim()==='浅色');
        light.click();
        await wait(()=>document.documentElement.classList.contains('theme-light'),'theme change');
        if(document.documentElement.dataset.storyosFont!=='chinese')throw Error('theme changed font mode');
      }
    }else if(c==='restore'){
      await wait(()=>document.documentElement.dataset.storyosFont==='chinese','persisted restore');
      if(!saved?.textContent?.includes('已保存到本机浏览器'))throw Error('restore feedback missing');
      balanced.click();
      await wait(()=>document.documentElement.dataset.storyosFont==='balanced','balanced restore');
      if(localStorage.getItem('storyos:font-preference:v1')!=='balanced')throw Error('balanced persisted incorrectly');
      if(getComputedStyle(document.body).fontFamily.indexOf('Inter')!==0)throw Error('balanced font fallback changed');
    }
    const tab=[...page.querySelectorAll('.ant-tabs-tab')].find(x=>x.textContent?.includes('生产管线'));
    if(!tab)throw Error('production tab missing');
    tab.click();
    await wait(()=>page.textContent?.includes('尚无已授权的生产配置读写接口'),'readonly production permission');
    if(page.querySelector('[aria-label="生产配置双栏工作区"] input')||page.querySelector('[aria-label="生产配置双栏工作区"] .ant-segmented'))throw Error('fake production controls');
    if(document.documentElement.scrollWidth>innerWidth+5)throw Error('horizontal overflow');
    document.body.dataset.reaSettingsResult='pass';
  }catch(e){document.body.dataset.reaSettingsResult='fail:'+(e.message||e)}
})+')('+JSON.stringify(c)+');</script></body>'));
 try{const r=spawnSync(chrome,['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--virtual-time-budget=40000','--window-size='+(c==='blocked'?'1024':'1440')+',920','--user-data-dir='+own,'--dump-dom',new URL('/'+name,base).href],{encoding:'utf8',timeout:105000,maxBuffer:8500000});
 const status=r.stdout?.match(/data-rea-settings-result="([^"]+)"/)?.[1]||'missing';
 if(status==='missing')console.log('BROWSER_DIAG',JSON.stringify({exit:r.status,signal:r.signal,stdoutLen:r.stdout?.length,stderrLen:r.stderr?.length,domTail:r.stdout?.slice(-1000),domHead:r.stdout?.slice(0,180),stderr:r.stderr?.slice(-160)}));
 assert.equal(status,'pass',c+' browser check '+status+' '+(r.stderr||'').slice(-550));console.log('PASS '+c+' font + settings browser');
 }finally{try{fs.unlinkSync(name)}catch{}if(c==='blocked')try{fs.rmSync(own,{recursive:true,force:true})}catch{}}
}console.log('REA_FONT_SETTINGS_CHROME_3_OF_3_PASS');
}finally{try{fs.rmSync(profile,{recursive:true,force:true})}catch{}}
