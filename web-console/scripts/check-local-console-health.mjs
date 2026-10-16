import {fileURLToPath} from 'node:url';
const apiPort=Number(process.env.STORYOS_LOCAL_EVIDENCE_PORT||19117);
const webPort=Number(process.env.STORYOS_LOCAL_CONSOLE_PORT||3100);
const valid=p=>Number.isInteger(p)&&p>=1024&&p<=65535;
if(!valid(apiPort)||!valid(webPort)||apiPort===webPort)throw Error('Invalid local console ports');
async function probe(url,validate){
 try{
  const response=await fetch(url,{signal:AbortSignal.timeout(4000),cache:'no-store'});
  if(!response.ok)return {ok:false,status:response.status};
  return {ok:await validate(response),status:response.status};
 }catch(error){return {ok:false,reason:error.name==='TimeoutError'?'timeout':'connection_failed'}}
}
export async function checkLocalConsole(){
 const base='http://127.0.0.1:';
 const results=await Promise.all([
  probe(base+webPort+'/',async r=>(await r.text()).includes('id="root"')),
  probe(base+apiPort+'/healthz',async r=>(await r.json()).code==='OK'),
  probe(base+webPort+'/api/v1/runtime/statuses?limit=1&offset=0',async r=>{
   const j=await r.json();return j.code==='OK'&&j.data?.total>0&&j.data.items?.[0]?.state_source==='local_workspace_episode_state_file';
  }),
  probe(base+webPort+'/api/v1/local-monitor/tasks',async r=>(await r.json()).code==='OK'),
  probe(base+webPort+'/api/v1/local-monitor/workers',async r=>(await r.json()).code==='OK'),
 ]);
 const names=['web','api','episode_stages','redis_tasks_readonly','redis_workers_readonly'];
 const endpoints=Object.fromEntries(names.map((name,i)=>[name,results[i]]));
 return {checked_at:new Date().toISOString(),web_port:webPort,api_port:apiPort,healthy:results.every(r=>r.ok),endpoints,execution_verified:false};
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]){
 const report=await checkLocalConsole();
 console.log(JSON.stringify(report));
 if(!report.healthy)process.exitCode=1;
}