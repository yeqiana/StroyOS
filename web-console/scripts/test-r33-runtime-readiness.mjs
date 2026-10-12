import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const raw=process.env.STORYOS_LOCAL_CONSOLE_URL || 'http://127.0.0.1:3100/';
const base=new URL(raw);
assert.equal(base.hostname,'127.0.0.1','R33 may inspect only explicit loopback read-only evidence, never production');
assert.equal(base.protocol,'http:','R33 requires local HTTP evidence');
assert.equal(base.username,'','credentials are prohibited');
assert.equal(base.password,'','credentials are prohibited');
const get=async(route)=>{
  const response=await fetch(new URL(route,base),{signal:AbortSignal.timeout(18000),cache:'no-store'});
  const payload=await response.json();
  return {http:response.status,payload};
};
const health=await get('/healthz');
assert.equal(health.http,200);
assert.equal(health.payload?.data?.status,'UP');
const list=await get('/api/v1/runtime/statuses?limit=100&offset=0');
assert.equal(list.http,200);
assert.equal(list.payload?.code,'OK');
const rows=list.payload?.data?.items;
assert.ok(Array.isArray(rows)&&rows.length>0,'read-only real episode evidence required');
assert.ok(rows.every(row=>row.episode_ref&&row.state_source==='local_workspace_episode_state_file'));
const total=list.payload.data.total;
assert.ok(Number.isInteger(total)&&total>=rows.length);
const current=rows[0];
const detail=await get('/api/v1/runtime/status?episode='+encodeURIComponent(current.episode_ref));
assert.equal(detail.http,200);
assert.equal(detail.payload?.code,'OK');
assert.equal(detail.payload?.data?.episode_ref,current.episode_ref,'identity-bound canonical detail required');
assert.equal(detail.payload?.data?.projection_level,'detail');
assert.equal(detail.payload?.data?.execution_status,'UNKNOWN');
assert.equal(detail.payload?.data?.heartbeat?.health,'unknown');
assert.equal(detail.payload?.data?.auto_recoverable,null);
const events=await get('/api/v1/runtime/events?limit=1&offset=0');
const registry=await get('/api/v1/agents');
assert.equal(events.http,403,'read-only local files cannot provide canonical events');
assert.equal(registry.http,403,'Agent Registry requires an authorized service');
assert.equal(events.payload?.code,'READ_ONLY_LOCAL_EVIDENCE');
assert.equal(registry.payload?.code,'READ_ONLY_LOCAL_EVIDENCE');
const report={
  schema_version:1,
  generated_at:new Date().toISOString(),
  source:'local_workspace_episode_state_file',
  environment:'localhost_readonly',
  checks:{
    health:{http:health.http,api_process_ready:true,runtime_online_proven:false},
    status_list:{http:list.http,records_loaded:rows.length,total,source_verified:true},
    episode_detail:{http:detail.http,identity_verified:true,execution_status:'UNKNOWN',heartbeat:'unknown',recoverable:null},
    event_stream:{http:events.http,capability:'not_authorized_in_local_mode'},
    agent_registry:{http:registry.http,capability:'not_authorized_in_local_mode'}
  },
  permission_policy:{
    can_start_workflow:false,can_retry_generation:false,can_modify_stage:false,
    can_auto_recover:false,can_publish:false,
    must_verify_before_real_canary:true
  },
  production_caveats:[
    'This report proves local disk-stage evidence, not real-time production Runtime.',
    'No production workers, provider tasks, releases or state mutations were invoked.',
    'Authorize canonical runtime, Episode owner fencing, budget and shared image permits before controlled canary.'
  ]
};
const out=path.resolve('../.storyos-tmp/ui-qa/r33/runtime-readiness.json');
fs.mkdirSync(path.dirname(out),{recursive:true});
fs.writeFileSync(out,JSON.stringify(report,null,2)+'\n');
console.log('PASS local runtime contract: '+rows.length+'/'+total+' identity-bound records, state+heartbeat UNKNOWN');
console.log('PASS local permission gates: events and Agent Registry 403, no production actions issued');
console.log('R33_READINESS_READONLY_2_OF_2_PASS '+out);
