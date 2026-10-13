import assert from 'node:assert/strict';
import {selectCurrentRuntimeDetail} from '../src/api/runtimeRecoveryAssessment.ts';

const old={episode_ref:'series/ep-01',execution_status:'FAILED',blocking_reason:'old failure'};
const newValue={episode_ref:'series/ep-02',execution_status:'RUNNING',current_action:'new episode'};
assert.equal(selectCurrentRuntimeDetail('series/ep-02',old),null,'stale response must not cross Episode boundary');
assert.equal(selectCurrentRuntimeDetail('series/ep-02',newValue),newValue,'current canonical details pass through');
assert.equal(selectCurrentRuntimeDetail('series/ep-02',{execution_status:'FAILED'}),null,'unlabelled details never displayed');
assert.equal(selectCurrentRuntimeDetail('',newValue),null,'missing selected episode always fails closed');
assert.equal(selectCurrentRuntimeDetail('series/ep-02',null),null,'missing detail is not present');
console.log('SINGLE_NODE_READONLY_DETAIL_SWITCH_IDENTITY_5_OF_5_PASS');
