import assert from 'node:assert/strict';
import { projectProductionProgress, PRODUCTION_MILESTONES } from '../src/api/productionProgress.ts';

const row = {schema_version:1, projection_level:'summary',episode_id:'test',episode_ref:'LOCAL_123',title:'测试',production_stage:'IDEA_LOCKED',state_source:'mysql_episode_state_read_only'};
const blocked = projectProductionProgress(row,{execution_status:'BLOCKED_RECORDED',current_action:'CREATIVE_STORY',blocking_reason:'STEP_BLOCKED',image_attempted_frames_observed:0});
assert.equal(blocked.state,'historical_block','recorded old failure must not become a live block');
assert.equal(blocked.completedSteps,1);
assert.equal(blocked.stagePercent,Math.round(100/7));
assert.equal(blocked.activeIndex,1);
assert.equal(blocked.blockedReason,null,'recorded old reason is not a current blocker');
assert.equal(blocked.framePercent,null);
assert.equal(PRODUCTION_MILESTONES[1],'故事与人物');

const awaiting = projectProductionProgress(row, {
  execution_status:'BLOCKED_RECORDED',
  current_action:'CREATIVE_STORY',
  blocking_reason:'STEP_BLOCKED',
  resume_admission: {
    status:'WAITING_EXPLICIT_START',
    story_gate_verified:true,
    read_only:true,
    production_authorization:false,
    image_entitlement_verified:false,
  },
  story_review_authority: {status:'PASS_VERIFIED',attempt:15,read_only:true},
});
assert.equal(awaiting.state,'waiting_start','A15 PASS cannot remain historically blocked');
assert.equal(awaiting.blockedReason,null);
assert.equal(awaiting.framePercent,null,'story PASS is not image production');

const currentFailure=projectProductionProgress(row,{
  execution_status:'BLOCKED',current_action:'CREATIVE_STORY',blocking_reason:'CURRENT_HARD_STOP'
});
assert.equal(currentFailure.state,'blocked','current explicit hard stop is still blocked');
assert.equal(currentFailure.blockedReason,'CURRENT_HARD_STOP');

const unverifiedPass=projectProductionProgress(row,{
  execution_status:'BLOCKED_RECORDED',current_action:'CREATIVE_STORY',
  resume_admission:{status:'WAITING_EXPLICIT_START',story_gate_verified:true,read_only:true,production_authorization:false},
  story_review_authority:{status:'UNVERIFIED',read_only:true},
});
assert.equal(unverifiedPass.state,'historical_block','unverified claim must not become ready');

const bare = projectProductionProgress(row,null);
assert.equal(bare.state,'unverified','MySQL stage alone must not imply running');
assert.equal(bare.stagePercent,14);
assert.equal(bare.action,null);

const provider = projectProductionProgress(row,{execution_status:'RESULT_RECORDED',current_action:'IMAGE_GENERATION',provider_call_observation:{provider_call_verified:true},image_progress:{expected_frames:20,accepted_frames:5}});
assert.equal(provider.state,'verified_generating');
assert.equal(provider.framePercent,25);
assert.equal(provider.activeIndex,4);

const partial = projectProductionProgress({...row,production_stage:'UNKNOWN'},{execution_status:'BLOCKED_RECORDED',current_action:'FRAME_CONTRACT',image_progress:{accepted_frames:0}});
assert.equal(partial.stagePercent,null,'unknown stage must not invent a percentage');
assert.equal(partial.activeIndex,2);
assert.equal(partial.framePercent,null);

const completed=projectProductionProgress({...row,production_stage:'PUBLISH_READY'},{execution_status:'COMPLETED'});
assert.equal(completed.completedSteps,7);
assert.equal(completed.stagePercent,100);
assert.equal(completed.state,'completed');

const safelyBounded=projectProductionProgress(row,{image_progress:{expected_frames:5,accepted_frames:6}});
assert.equal(safelyBounded.framePercent,100);
console.log('Production milestone tests: PASS (9 scenarios)');
