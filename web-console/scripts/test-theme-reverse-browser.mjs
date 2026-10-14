import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
const base=new URL(process.env.STORYOS_LOCAL_CONSOLE_URL||'http://127.0.0.1:3100/');
assert.equal(base.hostname,'127.0.0.1','only real local read-only console is allowed');
const chrome=process.env.CHROME_PATH||'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const html=fs.readFileSync('index.html','utf8');
const output=path.resolve('../.storyos-tmp/ui-qa/theme-reverse-p0');
fs.mkdirSync(output,{recursive:true});
const cases=[{"mode":"dark","width":1440,"tokens":{"--bg-app":"#0A0B0D","--bg-workspace":"#171717","--bg-surface":"#1C1E21","--bg-selected":"#343940","--text-primary":"#F4F6F8"}},{"mode":"light","width":1440,"tokens":{"--bg-app":"#FAFAFA","--bg-workspace":"#F1F2F4","--bg-surface":"#FFFFFF","--bg-selected":"#DEE5ED","--text-primary":"#1C2127"}},{"mode":"light-gradient","width":1440,"tokens":{"--bg-app":"#FAFAFA","--bg-workspace":"#F1F2F4","--bg-surface":"#FFFFFF","--bg-selected":"#E2E8EF","--text-primary":"#1C2127"}},{"mode":"light","width":1024,"tokens":{"--bg-app":"#FAFAFA","--bg-workspace":"#F1F2F4","--bg-surface":"#FFFFFF","--bg-selected":"#DEE5ED","--text-primary":"#1C2127"}}];
const validate=async function scenario(c){
 const wait=async(fn,label)=>{for(let i=0;i<260;i++){const v=fn();if(v)return v;await new Promise(r=>setTimeout(r,90))}throw Error('timeout '+label)};
 const hex=hex=>hex.replace('#','').match(/../g).map(x=>parseInt(x,16));
 const toRGB=hex=>`rgb(${hex.slice(1).match(/../g).map(x=>parseInt(x,16)).join(', ')})`;
 const rgb=c=>{const m=c.match(/rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)/);return m?[+m[1],+m[2],+m[3]]:null};
 const lum=arr=>arr.map(v=>{const u=v/255;return u<=0.04045?u/12.92:((u+0.055)/1.055)**2.4}).reduce((s,v,i)=>s+v*[0.2126,0.7152,0.0722][i],0);
 const contrast=(a,b)=>{const x=lum(rgb(a)),y=lum(rgb(b));return(Math.max(x,y)+0.05)/(Math.min(x,y)+0.05)};
 try{
  const nav=await wait(()=>document.querySelector('nav[aria-label="主要页面"]'),'nav');
  const sidebar=await wait(()=>document.querySelector('aside.storyos-sidebar'),'sidebar');
  const target=[...nav.querySelectorAll('button')].find(x=>x.textContent?.trim()==='作品与项目');
  if(!target)throw Error('library nav unavailable');
  target.click();
  const primary=await wait(()=>document.querySelector('.storyos-sidebar-create .os-action-primary'),'primary CTA');
  await wait(()=>nav.querySelector('button[aria-current="page"]')?.getAttribute('aria-label')==='作品与项目','active nav');
  const style=getComputedStyle(document.documentElement);
  const cssProp=k=>style.getPropertyValue(k).trim().toUpperCase();
  if(!document.documentElement.classList.contains('theme-'+c.mode))throw Error('wrong theme class '+c.mode);
  for(const [key,want] of Object.entries(c.tokens))if(cssProp(key)!==want)throw Error('wrong '+key+': '+cssProp(key)+' expected '+want);
  const sidebarBg=getComputedStyle(sidebar).backgroundColor;
  if(sidebarBg!==toRGB(c.tokens['--bg-workspace']))throw Error('sidebar background mismatch '+sidebarBg);
  const main=document.querySelector('main');
  if(!main)throw Error('main missing');
  const mainBg=getComputedStyle(main).backgroundColor;
  if(mainBg!==toRGB(c.tokens['--bg-app']))throw Error('workspace background mismatch '+mainBg);
  const primaryCss=getComputedStyle(primary);
  if(primaryCss.backgroundColor!==toRGB(c.tokens['--text-primary']))throw Error('CTA background '+primaryCss.backgroundColor);
  if(primaryCss.color!==toRGB(c.tokens['--bg-app']))throw Error('CTA text '+primaryCss.color);
  if(contrast(primaryCss.backgroundColor,primaryCss.color)<7)throw Error('CTA contrast below 7');
  // Nav selection uses a color transition; wait for the settled state before asserting an exact RGB.
  const activeEl=nav.querySelector('button[aria-current="page"]');
  await wait(()=>getComputedStyle(activeEl).backgroundColor===toRGB(c.tokens['--bg-selected']),'selected nav color transition');
  const active=getComputedStyle(activeEl);
  if(contrast(active.color,active.backgroundColor)<4.5)throw Error('nav contrast below 4.5');
  if(cssProp('--success')===cssProp('--info'))throw Error('semantic status colors merged');
  if(cssProp('--info')===cssProp('--text-primary'))throw Error('focus color became brand primary');
  const {THEME_PALETTES}=await import('/src/theme.ts');
  const jsTokens=THEME_PALETTES[c.mode];
  for(const [cssName,jsName] of Object.entries({'--bg-app':'bgApp','--bg-workspace':'bgWorkspace','--bg-surface':'bgSurface','--bg-selected':'bgSelected','--text-primary':'textPrimary','--info':'info'})){
   if(jsTokens[jsName].toUpperCase()!==cssProp(cssName))throw Error('AntD palette drift '+jsName);
  }
  if(document.documentElement.scrollWidth>innerWidth+4)throw Error('overflow viewport');
  document.body.dataset.themeReverse='pass';
  document.body.dataset.themeContrast=contrast(primaryCss.backgroundColor,primaryCss.color).toFixed(2);
 }catch(e){document.body.dataset.themeReverse='fail:'+String(e.message||e);}
};
for(const c of cases){
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'storyos-theme-reverse-'));
const entry='qa-theme-reverse-'+c.mode+'-'+c.width+'.html';
const seed='<script>localStorage.setItem("storyos_theme",'+JSON.stringify(c.mode)+');document.documentElement.classList.add("theme-"+'+JSON.stringify(c.mode)+');</script>';
fs.writeFileSync(entry,html.replace('</head>',seed+'</head>').replace('</body>','<script>('+validate.toString()+')('+JSON.stringify(c)+');</script></body>'));
const url=new URL('/'+entry,base).href;
const flags=['--headless=new','--no-sandbox','--disable-gpu','--disable-dev-shm-usage','--disable-extensions','--hide-scrollbars','--virtual-time-budget=30000','--window-size='+c.width+',900','--user-data-dir='+profile];
try{
 const result=spawnSync(chrome,[...flags,'--dump-dom',url],{encoding:'utf8',timeout:85000,maxBuffer:8500000});
 const status=result.stdout?.match(/data-theme-reverse="([^"]+)"/)?.[1]||'missing';
 assert.equal(status,'pass','browser palette check '+c.mode+' '+c.width+' '+status+' '+(result.stderr||'').slice(-300));
 const ratio=result.stdout?.match(/data-theme-contrast="([^"]+)"/)?.[1];
 if(c.width===1440){
  const png=path.join(output,'storyos-theme-'+c.mode+'-1440.png');
  const screenshot=spawnSync(chrome,[...flags,'--screenshot='+png,url],{encoding:'utf8',timeout:85000,maxBuffer:1000000});
  assert.equal(screenshot.status,0,'Chrome screenshot failed '+c.mode);
  assert.ok(fs.existsSync(png)&&fs.statSync(png).size>10000,'screenshot missing '+c.mode);
  console.log('PASS '+c.mode+' '+c.width+' contrast='+ratio+' screenshot='+png+' bytes='+fs.statSync(png).size);
 }else console.log('PASS '+c.mode+' '+c.width+' contrast='+ratio+' compact sidebar');
}finally{
 try{fs.unlinkSync(entry)}catch{}
 try{fs.rmSync(profile,{recursive:true,force:true})}catch{}
}
}
console.log('THEME_REVERSE_CHROME_4_OF_4_PASS');
