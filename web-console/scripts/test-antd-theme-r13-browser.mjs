import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3105/');
assert.equal(base.hostname,'127.0.0.1');
const html=fs.readFileSync('index.html','utf8');
const qa=[
 '(async()=>{try{',
 'const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
 'let btn;for(let i=0;i<160&&!btn;i++){btn=[...document.querySelectorAll("button")].find(x=>x.getAttribute("aria-label")==="账号菜单");if(!btn)await sleep(100)}',
 'if(!btn)throw Error("account menu missing");btn.click();',
 'let settings;for(let i=0;i<160&&!settings;i++){settings=[...document.querySelectorAll("[role=menu] button")].find(x=>x.getAttribute("aria-label")==="系统设置（账号菜单）");if(!settings)await sleep(100)}',
 'if(!settings)throw Error("settings inside account menu missing");settings.click();',
 'let container;for(let i=0;i<180&&!container;i++){container=document.querySelector("#codex-appearance-settings-view .ant-segmented");if(!container)await sleep(100)}',
 'if(!container)throw Error("Ant Design Segmented missing");',
 'let light=[...container.querySelectorAll("label")].find(x=>x.textContent?.trim()==="浅色");if(!light)throw Error("light option absent");light.click();',
 'for(let i=0;i<70&&!document.documentElement.classList.contains("theme-light");i++)await sleep(100);',
 'if(!document.documentElement.classList.contains("theme-light"))throw Error("theme did not switch to light");',
 'const dark=[...container.querySelectorAll("label")].find(x=>x.textContent?.trim()==="深色");if(!dark)throw Error("dark option absent");dark.click();',
 'for(let i=0;i<70&&!document.documentElement.classList.contains("theme-dark");i++)await sleep(100);',
 'if(!document.documentElement.classList.contains("theme-dark"))throw Error("theme did not switch back to dark");',
 'if(document.querySelectorAll("#codex-appearance-settings-view .ant-tabs").length!==1)throw Error("expected one standard tabs control");',
 'document.body.dataset.r13Theme="pass";',
 '}catch(e){document.body.dataset.r13Theme="fail:"+e.message}})();'
].join('\n');
const entry='qa-r13-theme-switch.html';
fs.writeFileSync(entry,html.replace('</body>','<script>'+qa+'</script></body>'));
try{
 const args=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--virtual-time-budget=27000','--window-size=1366,900','--user-data-dir='+path.resolve('../.storyos-tmp/ui-qa/r13-theme-profile'),'--dump-dom',new URL('/'+entry,base).href];
 const r=spawnSync(chrome,args,{encoding:'utf8',timeout:70000,maxBuffer:5000000});
 const mark=r.stdout?.match(/data-r13-theme="([^"]+)"/)?.[1]||'missing';
 assert.equal(mark,'pass','R13 Theme: '+mark+' '+r.stderr?.slice(-500));
 console.log('PASS Ant Design Tabs+Segmented render; light/dark switches real workspace theme');
}finally{try{fs.unlinkSync(entry)}catch{}}
