import type { RuntimeStatusDetail } from './platformApi';

export type RecoveryAssessmentCode =
  | 'local-evidence'
  | 'detail-unavailable'
  | 'unknown-state'
  | 'requires-human'
  | 'candidate-needs-authorization'
  | 'retry-already-reported'
  | 'failed-unverified'
  | 'not-recovery-situation';

/** Never combine an Episode summary with detail for a different or unlabelled Episode. */
export function runtimeDetailMatchesEpisode(expectedRef: string, detail: RuntimeStatusDetail | null): boolean {
  const actual = String(detail?.episode_ref || detail?.episode || '').trim();
  return Boolean(expectedRef && actual && expectedRef === actual);
}

export interface RecoveryAssessment {
  code: RecoveryAssessmentCode;
  title: string;
  explanation: string;
  /** An inspection result never authorizes a mutation or production retry. */
  canStartRecovery: false;
}

/**
 * Fail-closed recovery triage. Stage projections, file-backed observations and
 * unverified heartbeats can never imply a running Worker or grant retry rights.
 * Only the privileged Runtime owner may verify leases, gates, global image
 * permits and the current canonical state before any production transition.
 */
export function assessRuntimeRecovery(
  detail: RuntimeStatusDetail | null,
  source: string | null | undefined,
): RecoveryAssessment {
  const result = (code: RecoveryAssessmentCode, title: string, explanation: string): RecoveryAssessment =>
    ({ code, title, explanation, canStartRecovery: false });

  if (source === 'local_workspace_episode_state_file' || source === 'isolated-test') {
    return result(
      'local-evidence',
      '仅有历史阶段证据，不能判断是否需要恢复',
      '当前来源不是在线 Runtime；Writer、Worker 心跳、任务队列及授权门禁均未验证。禁止据此执行重试。',
    );
  }
  if (!detail) {
    return result(
      'detail-unavailable',
      '缺少执行详情，恢复状态未知',
      '阶段摘要只能证明已记录的生产阶段，不能推断任务是否运行、失败或有重试资格。',
    );
  }

  const status = String(detail.execution_status || '').trim().toUpperCase();
  if (!status || ['UNKNOWN', '-', 'NO_STATE', 'UNAVAILABLE'].includes(status)) {
    return result(
      'unknown-state',
      '执行状态未知，不允许推测可恢复',
      '必须先读取权威 Runtime 执行详情，并确认任务所属 Episode 与当前 Writer Owner。',
    );
  }

  if (detail.needs_user === true || Boolean(String(detail.blocking_reason || '').trim())) {
    return result(
      'requires-human',
      '需要人工核查阻塞或恢复前置条件',
      '接口明确指出需要人工介入或存在阻塞原因。请先核验实际证据和门禁，不能自动推进。',
    );
  }

  if (status === 'RETRYING') {
    return result(
      'retry-already-reported',
      '后端报告已有重试过程，不要重复发起',
      '先核对当前 Attempt、Writer Owner 与调度租约；不得因看到 RETRYING 就再创建一个生产尝试。',
    );
  }

  if (['FAILED', 'BLOCKED'].includes(status)) {
    if (detail.auto_recoverable === true && detail.needs_user === false) {
      return result(
        'candidate-needs-authorization',
        '后端报告恢复候选，尚未获得执行授权',
        '仍需在权威 Runtime 复核 Episode Writer、Generation Attempt、生产门禁和全局图片容量，当前只读页面不能直接发起。',
      );
    }
    return result(
      'failed-unverified',
      '异常已记录，但恢复资格尚未确认',
      '没有同时获得“无需人工”与“可自动恢复”的明确证据。先调查失败类型，禁止以盲重试代替诊断。',
    );
  }

  return result(
    'not-recovery-situation',
    '当前执行记录不属于已确认的恢复场景',
    '仅呈现服务端报告的执行状态；心跳和在线性须在权威 Runtime 独立核验，禁止从阶段摘要推导启动或完成。',
  );
}
