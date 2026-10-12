import assert from 'node:assert/strict';
import {usableRuntimeAuthority, runtimeEvidenceRows} from '../src/api/runtimeAuthorityPresentation.ts';

const epoch=Date.now();
const stamp=new Date(epoch).toISOString();
const scope='series/ep';
const source={
  task:'mysql_task_repository',
  attempt:'mysql_generation_attempt_authority',
  worker:'redis_worker_heartbeat',
  writer:'runtime_driver_owner_fence',
  capacity:'git_common_directory_os_permits',
};
function proof(){
  const evidence=Object.fromEntries(Object.entries(source).map(([name,from])=>[name,{
    status:name==='capacity'?'ADVISORY_ONLY':'READ_ONLY_VERIFIED',
    source:from,observed_at:stamp,read_only:true,
    ...(name==='worker'?{heartbeat_verified:true}:{}),
    ...(name==='writer'?{owner_fence_verified:true}:{}),
    ...(name==='capacity'?{advisory_snapshot_only:true,observed_busy:2,observed_available:3}:{})
  }]));
  return {schema_version:1,episode_ref:scope,scope:'AUTHORIZED_READ_ONLY',read_only:true,
    production_authorization:false,can_start:false,can_retry:false,
    can_publish:false,model_calls:0,global_image_capacity_policy:5,evidence};
}
const original=Date.now;
try{
  Date.now=()=>epoch+119000;
  const before=usableRuntimeAuthority(proof(),scope,false);
  assert.ok(before,'119 seconds old must remain valid before expiration');
  assert.equal(runtimeEvidenceRows(before,null,false).length,5);
  Date.now=()=>epoch+121000;
  assert.equal(usableRuntimeAuthority(proof(),scope,false),null,
               '120 seconds expired claims must be withdrawn');
  const expired=runtimeEvidenceRows(null,null,false);
  assert.ok(expired[2].children.includes('未验证'));
  assert.ok(expired[3].children.includes('尚未核验'));
  console.log('PASS R37 120-second stale proof rejected locally without a server call');

  Date.now=()=>epoch;
  const naive=proof();
  naive.evidence.worker.observed_at=stamp.replace(/Z$/,'');
  assert.equal(usableRuntimeAuthority(naive,scope,false),null,
               'timezone-less claims must never be verified');
  const changed=proof();
  changed.evidence.worker.observed_at=new Date(epoch+122000).toISOString();
  assert.equal(usableRuntimeAuthority(changed,scope,false),null,
               'future heartbeat cannot stand in for a fresh proof');
  const badCap=proof();
  badCap.evidence.capacity.advisory_snapshot_only=false;
  assert.equal(usableRuntimeAuthority(badCap,scope,false),null);
  const spoof=proof();
  spoof.evidence.worker.source='local_workspace_episode_state_file';
  assert.equal(usableRuntimeAuthority(spoof,scope,false),null);
  console.log('PASS R37 timezone, future, advisory and fake-source assertions');

  const local=proof();
  local.episode_ref='LOCAL_demo';
  local.scope='LOCAL_READ_ONLY_EVIDENCE';
  for(const key of Object.keys(local.evidence))local.evidence[key]={
    status:'UNAVAILABLE',source:null,observed_at:null,read_only:true,
    reason:'LOCAL_STAGE_ONLY'
  };
  assert.ok(usableRuntimeAuthority(local,'LOCAL_demo',true));
  assert.ok(runtimeEvidenceRows(local,null,true).every(x=>!x.children.includes('已核验')));
  console.log('PASS R37 local stage files cannot be promoted into Runtime authority');
}finally{Date.now=original}
console.log('R37_EVIDENCE_EXPIRY_AND_SOURCE_3_OF_3_PASS');
