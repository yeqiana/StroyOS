import assert from 'node:assert/strict';
import { assessRuntimeRecovery, runtimeDetailMatchesEpisode } from '../src/api/runtimeRecoveryAssessment.ts';

const detail = overrides => ({
  execution_status: 'FAILED',
  auto_recoverable: true,
  needs_user: false,
  ...overrides,
});
const cases = [
  { name:'local evidence always fail-closed', source:'local_workspace_episode_state_file', detail:detail(), code:'local-evidence' },
  { name:'isolated fixture cannot authorize retry', source:'isolated-test', detail:detail(), code:'local-evidence' },
  { name:'missing detail', source:'runtime', detail:null, code:'detail-unavailable' },
  { name:'unknown execution status', source:'runtime', detail:detail({execution_status:'UNKNOWN'}), code:'unknown-state' },
  { name:'needs human even with recovery flag', source:'runtime', detail:detail({needs_user:true}), code:'requires-human' },
  { name:'blocking reason dominates recovery flag', source:'runtime', detail:detail({blocking_reason:'fencing lease missing'}), code:'requires-human' },
  { name:'qualified recovery candidate still not authorized', source:'runtime', detail:detail(), code:'candidate-needs-authorization' },
  { name:'missing user clearance disallows candidate', source:'runtime', detail:detail({needs_user:null}), code:'failed-unverified' },
  { name:'missing auto-recovery flag disallows candidate', source:'runtime', detail:detail({auto_recoverable:null}), code:'failed-unverified' },
  { name:'blocked and incomplete evidence', source:'runtime', detail:detail({execution_status:'BLOCKED',auto_recoverable:false}), code:'failed-unverified' },
  { name:'already retrying must not create duplicate attempt', source:'runtime', detail:detail({execution_status:'RETRYING'}), code:'retry-already-reported' },
  { name:'running never implies recovery', source:'runtime', detail:detail({execution_status:'RUNNING'}), code:'not-recovery-situation' },
  { name:'completed never implies retry', source:'runtime', detail:detail({execution_status:'COMPLETED'}), code:'not-recovery-situation' },
  { name:'explicit false needs_user does not imply authorization', source:'runtime', detail:detail({auto_recoverable:false}), code:'failed-unverified' },
];

for(const {name,source,detail:payload,code} of cases){
 const result=assessRuntimeRecovery(payload,source);
 assert.equal(result.code,code,name);
 assert.equal(result.canStartRecovery,false,'no UI diagnosis can authorize a task mutation: '+name);
 assert.ok(result.title.length>8&&result.explanation.length>12,'complete rationale: '+name);
 console.log('PASS '+name+' => '+code);
}
console.log('R33_RECOVERY_FAIL_CLOSED_'+cases.length+'_OF_'+cases.length+'_PASS');
const identityCases=[
  {name:'exact canonical identity',expected:'LOCAL_abc',response:{episode_ref:'LOCAL_abc'},valid:true},
  {name:'alternate canonical episode field',expected:'series/episode',response:{episode:'series/episode'},valid:true},
  {name:'cross-Episode reply is rejected',expected:'LOCAL_a',response:{episode_ref:'LOCAL_b'},valid:false},
  {name:'missing identity cannot be merged',expected:'LOCAL_a',response:{execution_status:'FAILED'},valid:false},
  {name:'missing detail cannot be merged',expected:'LOCAL_a',response:null,valid:false},
];
for (const {name,expected,response,valid} of identityCases) {
  assert.equal(runtimeDetailMatchesEpisode(expected,response),valid,name);
  console.log('PASS '+name);
}
console.log('R33_EPISODE_DETAIL_IDENTITY_'+identityCases.length+'_OF_'+identityCases.length+'_PASS');
