import assert from 'node:assert/strict';
import {runtimeEvidenceRows, usableRuntimeAuthority} from '../src/api/runtimeAuthorityPresentation.ts';

const now = () => new Date().toISOString();
const EP = 'series/episode';
const snapshot = () => ({
  schema_version: 1, episode_ref: EP, scope: 'AUTHORIZED_READ_ONLY',
  read_only: true, production_authorization: false,
  can_start: false, can_retry: false, can_publish: false,
  model_calls: 0, global_image_capacity_policy: 5,
  evidence: {
    task: {status: 'READ_ONLY_VERIFIED', source: 'mysql_task_repository', observed_at: now(), read_only: true, task_count: 4},
    attempt: {status: 'READ_ONLY_VERIFIED', source: 'mysql_generation_attempt_authority', observed_at: now(), read_only: true, attempt_count: 2, unresolved: true, unknown: true},
    worker: {status: 'READ_ONLY_VERIFIED', source: 'redis_worker_heartbeat', observed_at: now(), read_only: true, heartbeat_verified: true},
    writer: {status: 'READ_ONLY_VERIFIED', source: 'runtime_driver_owner_fence', observed_at: now(), read_only: true, owner_fence_verified: true},
    capacity: {status: 'ADVISORY_ONLY', source: 'git_common_directory_os_permits', observed_at: now(), read_only: true, advisory_snapshot_only: true, observed_busy: 1, observed_available: 4},
  },
});
const valid = snapshot();
assert.ok(usableRuntimeAuthority(valid, EP, false));
const rows = runtimeEvidenceRows(valid, null, false);
assert.equal(rows.length, 5);
assert.ok(rows[0].children.includes('4 条'));
assert.ok(rows[1].children.includes('OUTCOME_UNKNOWN'));
assert.ok(rows[1].children.includes('禁止自动重试'));
assert.ok(rows[2].children.includes('MySQL Task 归属 + TTL'));
assert.ok(rows[3].children.includes('唯一 Owner + 活跃 Lease'));
assert.ok(rows[4].children.includes('非预约许可'));
assert.equal(valid.production_authorization, false);
assert.equal(valid.can_retry, false);
console.log('PASS R36 verified-source presentation keeps UNKNOWN non-retriable and OS capacity advisory');

const reject=(mutate, description)=>{
  const x=structuredClone(snapshot());
  mutate(x);
  assert.equal(usableRuntimeAuthority(x, EP, false), null, description);
};
reject(x=>x.episode_ref='foreign/story', 'cross-episode report must not render');
reject(x=>x.evidence.worker.heartbeat_verified=false, 'worker without TTL proof');
reject(x=>x.evidence.writer.owner_fence_verified=false, 'writer without fencing proof');
reject(x=>x.evidence.worker.source='untrusted_persisted_file','forged Redis source');
reject(x=>x.evidence.writer.source='plain_pid_file','PID not fencing');
reject(x=>x.evidence.worker.observed_at='2020-01-01T00:00:00Z','stale heartbeat');
reject(x=>x.evidence.attempt.observed_at='2040-01-01T00:00:00Z','future timestamp');
reject(x=>x.evidence.capacity.advisory_snapshot_only=false,'capacity is not a permit');
reject(x=>x.evidence.capacity.observed_available=5,'busy + free must be five');
reject(x=>x.evidence.capacity.status='READ_ONLY_VERIFIED','capacity must stay advisory');
reject(x=>x.can_retry=true,'no authority to retry');
reject(x=>x.production_authorization=true,'no production authorization');
console.log('PASS R36 12 forged, stale, foreign, lease and capacity claims rejected');

const missing=structuredClone(snapshot());
missing.evidence.worker={
  status:'UNAVAILABLE',read_only:true,reason:'WORKER_HEARTBEAT_UNVERIFIED',source:null,
};
missing.evidence.writer={
  status:'UNAVAILABLE',read_only:true,reason:'WRITER_FENCE_UNVERIFIED',source:null,
};
assert.ok(usableRuntimeAuthority(missing,EP,false));
const failRows=runtimeEvidenceRows(missing,null,false);
assert.ok(failRows[2].children.includes('TTL / 心跳未验证'));
assert.ok(failRows[3].children.includes('唯一租约 / fencing 未验证'));
assert.ok(!failRows.some(x=>x.children.includes('Worker 在线')));
console.log('PASS R36 unavailable evidence names root reasons without asserting online status');

const local=structuredClone(snapshot());
local.scope='LOCAL_READ_ONLY_EVIDENCE';
local.episode_ref='LOCAL_123';
for(const key of Object.keys(local.evidence)){
  local.evidence[key]={status:'UNAVAILABLE',read_only:true,source:null,observed_at:null,reason:'LOCAL_STAGE_ONLY'};
}
assert.ok(usableRuntimeAuthority(local,'LOCAL_123',true));
assert.ok(runtimeEvidenceRows(local,null,true).every(x=>!x.children.includes('已核验')));
const forged=structuredClone(local);
forged.evidence.worker.reason='FAKE_LOCAL_HEARTBEAT';
assert.equal(usableRuntimeAuthority(forged,'LOCAL_123',true),null);
console.log('PASS R36 local evidence strictly non-authoritative');
console.log('R36_RUNTIME_AUTHORITY_PRESENTATION_4_OF_4_PASS');
