import type { RuntimeStatusDetail, RuntimeStatusSummary } from './platformApi';

export const PRODUCTION_MILESTONES = [
  '创意立项',
  '故事与人物',
  '分镜提示词',
  '视觉基准',
  '正式出图',
  '审核与修复',
  '发布准备',
] as const;

export type ProductionMonitorState = 'verified_generating' | 'blocked' | 'completed' | 'recorded_activity' | 'waiting_start' | 'historical_block' | 'unverified';

const completedByStage: Record<string, number> = {
  IDEA_LOCKED: 1,
  STORY_LOCKED: 2,
  STORYBOARD_LOCKED: 3,
  VISUAL_CALIBRATED: 4,
  PRODUCTION_PASSED: 6,
  PUBLISH_READY: 7,
  PUBLISHED: 7,
  DATA_REVIEWED: 7,
};

function currentStepIndex(action: string | null | undefined): number | null {
  const key = (action || '').toUpperCase();
  if (/CREATIVE_STORY|CHARACTER|STORY_LOCK|STORY_REVIEW/.test(key)) return 1;
  if (/STORYBOARD|FRAME_CONTRACT|FRAME_PLAN|FRAME_PROMPT|PROMPT_AUTHOR/.test(key)) return 2;
  if (/VISUAL|M00|STYLE_LOCK|REFERENCE_IMAGE/.test(key)) return 3;
  if (/IMAGE_GENERAT|IMAGE_BATCH|GENERAT|DISPATCH|IMAGE_PRODUCTION/.test(key)) return 4;
  if (/REPAIR|REVIEW|AUDIT|QUALITY|SEMANTIC/.test(key)) return 5;
  if (/SUBTITLE|RELEASE|PUBLISH|FINAL/.test(key)) return 6;
  return null;
}

export interface ProductionProgressProjection {
  state: ProductionMonitorState;
  stateLabel: string;
  evidenceLabel: string;
  completedSteps: number | null;
  stagePercent: number | null;
  activeIndex: number | null;
  action: string | null;
  blockedReason: string | null;
  acceptedFrames: number | null;
  expectedFrames: number | null;
  framePercent: number | null;
}

export function projectProductionProgress(row: RuntimeStatusSummary, detail?: RuntimeStatusDetail | null): ProductionProgressProjection {
  const stage = String(detail?.production_stage || row.production_stage || '').toUpperCase();
  const completed = Object.prototype.hasOwnProperty.call(completedByStage, stage) ? completedByStage[stage] : null;
  const currentAction = detail?.current_action || detail?.next_step || null;
  const actionIndex = currentStepIndex(currentAction);
  const recordStatus = String(detail?.execution_status || '').toUpperCase();
  // A finite STEP_FAILED trace only proves a historical error. It is not
  // current Driver liveness, and may precede an independently verified PASS.
  const historicalFailure = ['BLOCKED_RECORDED', 'FAILURE_RECORDED', 'FAILED_RECORDED'].includes(recordStatus);
  const currentBlocked = ['BLOCKED', 'FAILED', 'NEEDS_USER', 'HARD_STOP', 'CURRENT_BLOCKED'].includes(recordStatus);
  const resumeVerified = detail?.resume_admission?.status === 'WAITING_EXPLICIT_START' &&
    detail?.resume_admission?.story_gate_verified === true &&
    detail?.story_review_authority?.status === 'PASS_VERIFIED';
  const providerVerified = detail?.provider_call_observation?.provider_call_verified === true;
  const completedRun = ['COMPLETED', 'COMPLETE', 'SUCCESS', 'SUCCEEDED'].includes(recordStatus);
  const state: ProductionMonitorState =
    currentBlocked ? 'blocked' : providerVerified ? 'verified_generating' :
    completedRun ? 'completed' : resumeVerified ? 'waiting_start' :
    historicalFailure ? 'historical_block' :
    recordStatus && !['UNKNOWN', 'NO_STATE', '-'].includes(recordStatus) ? 'recorded_activity' : 'unverified';
  const activeIndex = actionIndex !== null && completed !== null ? Math.max(completed, actionIndex) :
    actionIndex ?? (completed === null || completed >= PRODUCTION_MILESTONES.length ? null : completed);
  const accepted = detail?.image_progress?.accepted_frames;
  const expected = detail?.image_progress?.expected_frames;
  const acceptedFrames = Number.isInteger(accepted) && (accepted as number) >= 0 ? accepted as number : null;
  const expectedFrames = Number.isInteger(expected) && (expected as number) > 0 ? expected as number : null;

  return {
    state,
    stateLabel: state === 'blocked' ? '当前阻断' : state === 'verified_generating' ? '已核验出图中' :
      state === 'completed' ? '已记录完成' : state === 'waiting_start' ? '待手动启动' :
      state === 'historical_block' ? '历史失败记录' :
      state === 'recorded_activity' ? '存在执行记录' : '运行未核验',
    evidenceLabel: state === 'verified_generating' ? 'Provider 调用窗口已核验' :
      state === 'blocked' ? '当前运行门禁报告阻断' :
      state === 'waiting_start' ? '后续正式故事审核已通过，等待明确授权启动 Driver' :
      state === 'historical_block' ? '历史 STEP_FAILED 不能证明当前仍阻断' :
      state === 'completed' ? '执行结果记录了完成' :
      state === 'recorded_activity' ? '仅有历史节点记录，未证明当前在线' : '尚无可核验在线证据',
    completedSteps: completed,
    stagePercent: completed === null ? null : Math.round(completed / PRODUCTION_MILESTONES.length * 100),
    activeIndex,
    action: currentAction,
    blockedReason: state === 'blocked' ? detail?.blocking_reason || recordStatus : null,
    acceptedFrames,
    expectedFrames,
    framePercent: expectedFrames !== null && acceptedFrames !== null ? Math.round(Math.min(acceptedFrames, expectedFrames) / expectedFrames * 100) : null,
  };
}
