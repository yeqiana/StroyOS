import assert from 'node:assert/strict';
import { runtimeEvidenceRows, usableRuntimeAuthority } from '../src/api/runtimeAuthorityPresentation.ts';

const names=['task','attempt','worker','writer','capacity'];
const local=()=>{
  const evidence=Object.fromEntries(names.map(name=>[name,{
    status:'UNAVAILABLE',source:null,observed_at:null,reason:'LOCAL_STAGE_ONLY',read_only:true
  }]));
  return {schema_version:1,episode_ref:'LOCAL_abc',scope:'LOCAL_READ_ONLY_EVIDENCE',
    read_only:true,production_authorization:false,can_start:false,can_retry:false,
    can_publish:false,model_calls:0,global_image_capacity_policy:5,evidence};
};
const expectLocal=local();
assert.deepEqual(usableRuntimeAuthority(expectLocal,'LOCAL_abc',true),expectLocal);
assert.equal(usableRuntimeAuthority(local(),'LOCAL_foreign',true),null,'cross episode');
assert.equal(usableRuntimeAuthority({...local(),production_authorization:true},'LOCAL_abc',true),null);
assert.equal(usableRuntimeAuthority({...local(),can_retry:true},'LOCAL_abc',true),null);
assert.equal(usableRuntimeAuthority({...local(),model_calls:1},'LOCAL_abc',true),null);
assert.equal(usableRuntimeAuthority({...local(),scope:'AUTHORIZED_READ_ONLY'},'LOCAL_abc',true),null);
assert.equal(usableRuntimeAuthority({...local(),evidence:{...local().evidence,attempt:{
  status:'READ_ONLY_VERIFIED',source:'mysql_generation_attempt_authority',
  read_only:true,observed_at:new Date().toISOString()
}}},'LOCAL_abc',true),null,'local origin forbids authoritative claims');
assert.equal(usableRuntimeAuthority({...local(),evidence:{}},'LOCAL_abc',true),null);
const localRows=runtimeEvidenceRows(expectLocal,{execution_status:'RUNNING',heartbeat:{health:'UP'}},true);
assert.equal(localRows.length,5);
assert.ok(localRows[0].children.includes('未接入'));
assert.ok(localRows[2].children.includes('未验证'));
assert.ok(localRows[4].children.includes('当前持锁数未接入'));
assert.ok(!JSON.stringify(localRows).includes('RUNNING'));
console.log('PASS local R35 identity, action-denial, source spoofing, five unavailable evidence cells');

const authoritative={
  ...local(),episode_ref:'ep-one',scope:'AUTHORIZED_READ_ONLY',
  evidence:{
    task:{status:'READ_ONLY_VERIFIED',source:'mysql_task_repository',
      observed_at:new Date().toISOString(),task_count:3,read_only:true},
    attempt:{status:'READ_ONLY_VERIFIED',source:'mysql_generation_attempt_authority',
      observed_at:new Date().toISOString(),attempt_count:2,unresolved:true,read_only:true},
    worker:{status:'READ_ONLY_VERIFIED',source:'redis_worker_heartbeat',
      observed_at:new Date().toISOString(),heartbeat_verified:true,read_only:true},
    writer:{status:'READ_ONLY_VERIFIED',source:'runtime_driver_owner_fence',
      observed_at:new Date().toISOString(),owner_fence_verified:true,read_only:true},
    capacity:{status:'ADVISORY_ONLY',source:'git_common_directory_os_permits',
      observed_at:new Date().toISOString(),observed_busy:2,observed_available:3,advisory_snapshot_only:true,read_only:true},
  }
};
const valid=usableRuntimeAuthority(authoritative,'ep-one',false);
assert.ok(valid);
const rows=runtimeEvidenceRows(valid,{execution_status:'UNKNOWN'},false);
assert.ok(rows[0].children.includes('3 条'));
assert.ok(rows[1].children.includes('未决尝试'));
assert.ok(rows[2].children.includes('心跳来源已核验'));
assert.ok(rows[3].children.includes('fencing 来源已核验'));
assert.ok(rows[4].children.includes('2/5 占用'));
assert.ok(rows[4].children.includes('非预约许可'));
assert.ok(rows.every(row=>!row.children.includes('允许重试')));
console.log('PASS authorized future reader displays proven facts without granting dispatch');

const swapped=structuredClone(authoritative);
swapped.evidence.worker.source='unverified_fake_backend';
const guarded=runtimeEvidenceRows(usableRuntimeAuthority(swapped,'ep-one',false),null,false);
assert.ok(guarded[2].children.includes('未验证'),'spoofed reader must not infer worker liveness');
console.log('PASS unverified reader cannot impersonate a canonical Worker source');
console.log('R35_FRONTEND_AUTHORITY_GUARD_3_OF_3_PASS');
