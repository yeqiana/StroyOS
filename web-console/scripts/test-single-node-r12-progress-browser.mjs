import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawn,spawnSync} from 'node:child_process';
const web=process.cwd(),root=path.resolve(web,'..'),port=3194,apiPort=19924;
const chrome='C:/Program Files/Google/Chrome/Application/chrome.exe';
const base='http://127.0.0.1:'+port,qa='qa-task-frame-r12.html';
const screenshot=path.join(root,'.storyos-tmp/ui-qa/real-task-frame-r12-1440.png');
assert.ok(fs.existsSync(chrome));
assert.ok(!fs.existsSync(path.join(web,qa)),'refuse overwriting an existing QA HTML page');
const runtime=spawn(process.execPath,['web-console/scripts/launch-local-real-console.mjs'],{
 cwd:root,env:{...process.env,STORYOS_LOCAL_CONSOLE_PORT:String(port),
 STORYOS_LOCAL_EVIDENCE_PORT:String(apiPort)},windowsHide:true,stdio:['ignore','pipe','pipe']});
let childLogs='';runtime.stdout.on('data',x=>childLogs=(childLogs+x.toString()).slice(-3000));runtime.stderr.on('data',x=>childLogs=(childLogs+x.toString()).slice(-3000));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function ready(){
 for(let n=0;n<100;n++){
  if(runtime.exitCode!==null)throw Error('Test-only server stopped code='+runtime.exitCode+' '+childLogs.slice(-1250));
  try{const r=await fetch(base+'/api/v1/runtime/statuses?limit=100&offset=0',{signal:AbortSignal.timeout(2500)});
    if(r.ok){const data=(await r.json()).data;if(data.total>0)return data;}}catch{}
  await wait(300);
 }
 throw Error('recorded monitor API did not start');
}
try{
 const listing=await ready(),detailed=[];
 assert.equal(listing.total,11,'Internal test and archive directories must not be production Episodes');

 const mysqlCoverage={available:0,unavailable:0,reasons:{}};
 for(const row of listing.items){
  const response=await fetch(base+'/api/v1/runtime/status?episode='+encodeURIComponent(row.episode_ref));
  if(!response.ok)continue;
  const data=(await response.json()).data;
  if(data?.mysql_monitor?.available)mysqlCoverage.available++;
  else {mysqlCoverage.unavailable++;const reason=data?.mysql_monitor?.reason||"UNKNOWN";mysqlCoverage.reasons[reason]=(mysqlCoverage.reasons[reason]||0)+1;}
  if(data?.frame_records?.length===20)detailed.push({title:row.title,detail:data});
 }
 const heartResp=await fetch(base+'/api/v1/local-monitor/workers');
 assert.equal(heartResp.status,200);
 const heartbeat=(await heartResp.json()).data;
 assert.equal(heartbeat.scope,'LOCAL_REDIS_HEARTBEAT_OBSERVATION');
 assert.equal(heartbeat.read_only,true);
 assert.equal(heartbeat.worker_execution_verified,false);
 assert.equal(heartbeat.writer_owner_verified,false);
 assert.equal(heartbeat.record_count,heartbeat.fresh_heartbeats+heartbeat.stale_heartbeats+heartbeat.unverified_heartbeats);
 assert.ok(!JSON.stringify(heartbeat).includes('worker_id'));
 const forbiddenHeart=await fetch(base+'/api/v1/local-monitor/workers',{method:'POST',body:'{}'});
 assert.equal(forbiddenHeart.status,403);
 assert.ok(detailed.length,'real per-frame evidence missing');
 assert.equal(mysqlCoverage.available,11,'Every canonical Episode needs verified MySQL identity');
 assert.equal(mysqlCoverage.unavailable,0,'No canonical Episode can have an unresolved identity');
 assert.ok(listing.items.every(x=>!x.title.startsWith('driver-') && !String(x.episode_ref).includes('_tests')));

 const sample=detailed.find(r=>r.title==='婚礼前夜' && r.detail.queue_summary?.recorded_items>0)||detailed[0];
 assert.equal(sample.detail.execution_status,'UNKNOWN');
 assert.equal(sample.detail.heartbeat.health,'unknown');
 assert.equal(sample.detail.monitoring_scope,'RECORDED_FILES_ONLY');
 assert.equal(sample.detail.mysql_monitor?.available,true,'True READ_ONLY_MYSQL not enabled: '+sample.detail.mysql_monitor?.reason);
 assert.equal(sample.detail.mysql_monitor?.database_identity_verified,true);
 assert.equal(sample.detail.mysql_monitor?.read_only_grants_verified,true);
 for(const forbidden of ['STORYOS_MONITOR_MYSQL_RO_PASSWORD','mysql-monitor-ro.json','LEASE_TOKEN','OWNER_ID'])assert.ok(!JSON.stringify(sample.detail).includes(forbidden));
 assert.equal(sample.detail.writer_owner_observation?.status,'UNKNOWN');
 assert.equal(sample.detail.writer_owner_observation?.kernel_lock_verified,false);
 assert.equal(sample.detail.writer_owner_observation?.producer_process_verified,false);
 assert.equal(sample.detail.recorded_production_progress?.available,true);
 assert.equal(sample.detail.recorded_production_progress?.scope,"VERIFIED_EPISODE_RECORDED_PROGRESS");
 assert.ok(sample.detail.recorded_production_progress?.recent_frame?.frame>=1);
 assert.equal(sample.detail.recorded_production_progress?.verified_current_frame,null);
 assert.equal(sample.detail.recorded_production_progress?.verified_current_task,null);
 assert.equal(sample.detail.recorded_production_progress?.provider_call_verified,false);
 assert.equal(sample.detail.recorded_production_progress?.stalled_verified,false);
 assert.ok(sample.detail.recorded_production_progress?.frame_attempts?.length>0);
 assert.ok(!JSON.stringify(sample.detail.recorded_production_progress).includes("LEASE_TOKEN"));
 assert.equal(sample.detail.frame_records.length,20);
 assert.equal(sample.detail.can_retry,false);
 const blocked=await fetch(base+'/api/v1/runtime/statuses',{method:'POST',body:'{}'});
 assert.equal(blocked.status,403);
 const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
 const injection='<script>'+[
  '(async()=>{try{',
  'const expected='+JSON.stringify(sample.title)+';',
  'const sleep=ms=>new Promise(r=>setTimeout(r,ms));',
  'async function find(f,max=200){for(let i=0;i<max;i++){const v=f();if(v)return v;await sleep(100)}throw Error("missing UI element")}',
  'const nav=await find(()=>[...document.querySelectorAll(\'nav[aria-label="主要页面"] button\')].find(b=>b.textContent.trim()==="生产监控"));',
  'nav.click();',
  'const hb=await find(()=>{const v=document.querySelector("section[aria-label^=Redis]");return v&&v.textContent.includes("采集记录")?v:null;},140);',
  'if(!hb.textContent.includes("心跳过期")||!hb.textContent.includes("不等于 Worker"))throw Error("heartbeat freshness disclaimers absent");',
  'const stageBtn=[...document.querySelectorAll("button")].find(x=>x.textContent.includes("阶段证据 ("));if(stageBtn&&!stageBtn.textContent.includes("阶段证据 (11)"))throw Error("unexpected real stage count "+stageBtn.textContent);',
  'const row=await find(()=>[...document.querySelectorAll("tbody tr")].find(x=>x.textContent.includes(expected)),230);',
  'const detail=row.querySelector(\'button[aria-label^="查看权威阶段"]\')||[...row.querySelectorAll("button")].find(b=>b.textContent.includes("详情"));',
  'if(!detail)throw Error("detail action not found");detail.click();',
  'const evidence=await find(()=>document.querySelector(\'[aria-label="真实生产记录明细"]\'),170);',
  'const text=evidence.textContent||"";',
  'const writer=await find(()=>document.querySelector("section[aria-label^=Driver]"),80);',
  'if(!writer.textContent.includes("尚无可核验")||!writer.textContent.includes("不等于内核锁"))throw Error("Writer claim must remain unavailable without fresh canonical Driver");',
  'const progress=await find(()=>document.querySelector("section[aria-label^=真实制作进度]"),90);',
  'if(!progress.textContent.includes("最近记录的生图帧")||!progress.textContent.includes("是否卡住")||!progress.textContent.includes("无法判定")||!progress.textContent.includes("历史耗时"))throw Error("R12 frame progress truth statement missing");',
  'if(progress.querySelectorAll("tbody tr").length<1)throw Error("R12 per-frame SQL projection missing");',
  'const sql=await find(()=>document.querySelector("section[aria-label^=MySQL]"),80);',
  'if(!sql.textContent.includes("数据库身份与只读事务已核验")||!sql.textContent.includes("Writer 执行权：未验证"))throw Error("MySQL real SELECT-only evidence not visible");',
  'sql.scrollIntoView({block:"start",behavior:"instant"});',
  'writer.scrollIntoView({block:"start",behavior:"instant"});',
  'progress.scrollIntoView({block:"start",behavior:"instant"});',
  'if(!text.includes("逐帧制作记录")||!text.includes("账本状态")||!text.includes("在线未确认"))throw Error("true production evidence not visible");',
  'if(evidence.querySelectorAll("tbody tr").length<10)throw Error("per-frame table not rendered");',
  'document.body.dataset.monitorR12="pass";',
  '}catch(e){document.body.dataset.monitorR12="fail:"+e.message}})();'
 ].join('\n')+'</script>';
 fs.writeFileSync(path.join(web,qa),html.replace('</body>',injection+'</body>'),'utf8');
 const chromeArgs=['--headless=new','--disable-gpu','--no-sandbox','--disable-dev-shm-usage','--virtual-time-budget=35000','--window-size=1440,900','--user-data-dir='+path.join(root,'.storyos-tmp/ui-qa/r12-task-frame-profile')];
 const rendered=spawnSync(chrome,[...chromeArgs,'--dump-dom',base+'/'+qa],{encoding:'utf8',timeout:85000,maxBuffer:5500000,windowsHide:true});
 const match=rendered.stdout?.match(/data-monitor-r12="([^"]+)"/)?.[1]||'MISSING';
 assert.equal(match,'pass','Real Chrome drawer failed: '+match+' '+(rendered.stderr||'').slice(-350));
 fs.mkdirSync(path.dirname(screenshot),{recursive:true});
 const shot=spawnSync(chrome,[...chromeArgs,'--screenshot='+screenshot,base+'/'+qa],{encoding:'utf8',timeout:85000,windowsHide:true});
 assert.ok(shot.status===0&&fs.existsSync(screenshot)&&fs.statSync(screenshot).size>3000);
 console.log('R12_RECORDED_PROGRESS frame='+sample.detail.recorded_production_progress.recent_frame.frame+' frame_samples='+sample.detail.recorded_production_progress.frame_attempts.length+' active_verified='+Boolean(sample.detail.recorded_production_progress.verified_current_frame)+' stalled_verified='+sample.detail.recorded_production_progress.stalled_verified);
 console.log('R11_WRITER_PRODUCER_ACTUAL '+sample.detail.writer_owner_observation.status+' lock_verified='+sample.detail.writer_owner_observation.kernel_lock_verified);
 console.log('REAL_MYSQL_COVERAGE '+JSON.stringify(mysqlCoverage));
 console.log('PASS_LIVE_MYSQL_MONITOR episode='+sample.title+' tasks='+sample.detail.mysql_monitor.task_records.length+' production_attempts='+sample.detail.mysql_monitor.production_attempt_records.length+' generation_attempts='+sample.detail.mysql_monitor.generation_attempt_records.length+' writer_verified='+sample.detail.mysql_monitor.writer_owner_verified);
 console.log('PASS_REDIS_HEARTBEAT_READONLY observed='+heartbeat.record_count+' fresh='+heartbeat.fresh_heartbeats+' stale='+heartbeat.stale_heartbeats+' unavailable='+!heartbeat.available);
 console.log('PASS_TRUE_RECORDED_MONITOR_CHROME episode_records='+listing.total+' per_frame=20 with_queue='+Boolean(sample.detail.queue_summary?.recorded_items)+' no_mutation_403=true screenshot_bytes='+fs.statSync(screenshot).size);
}finally{
 try{fs.unlinkSync(path.join(web,qa))}catch{}
 if(runtime.exitCode===null)spawnSync('taskkill',['/PID',String(runtime.pid),'/T','/F'],{encoding:'utf8',timeout:12000,windowsHide:true});
}
