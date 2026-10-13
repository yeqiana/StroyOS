import type { RuntimeStatusDetail } from './platformApi';

/** Recorded evidence counts are independent samples. Never infer a SQL FK from
 * equal titles, timestamps, frame numbers, or the presence of a Driver heartbeat.
 */
export function recordedTraceCoverage(detail: RuntimeStatusDetail | null | undefined) {
  const mysql=detail?.mysql_monitor;
  if (!mysql?.available || !mysql.database_identity_verified || !mysql.read_only_grants_verified) {
    return {verified:false,taskCount:0,productionAttemptCount:0,generationAttemptCount:0,unresolvedCount:0,traceLinked:false,complete:false};
  }
  return {
    verified:true,
    taskCount:mysql.task_records.length,
    productionAttemptCount:mysql.production_attempt_records.length,
    generationAttemptCount:mysql.generation_attempt_records.length,
    unresolvedCount:mysql.generation_attempt_records.filter(x=>x.status==='OUTCOME_UNKNOWN').length,
    // Current readonly MySQL projection does not return a correlated Attempt ID
    // and end-to-end Trace ID. The UI must not claim chain-of-custody completion.
    traceLinked:false,
    complete:false,
  };
}
