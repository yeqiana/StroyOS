import assert from 'node:assert/strict';
import {reconcileRuntimeCatalog} from '../src/api/runtimeCatalogReconciliation.ts';
import {recordedTraceCoverage} from '../src/api/recordedTraceCoverage.ts';

const ep=(id,code,title)=>({id,code,title});
const live=(business_episode_id,title,id='LOCAL_1234567890abcdef12345678')=>({
  episode_ref:id,business_episode_id,title,state_source:'local_workspace_episode_state_file'
});
const base=[ep('a','09-05','婚礼前夜'),ep('b','11-01','仲夏夜惊魂'),ep('ep-home-1','NEW','用户本地草稿')];
const rows=[live('09-05','婚礼前夜'),live('11-01','同名改版','LOCAL_abcdef1234567890abcdef12')];
const results=reconcileRuntimeCatalog(base,rows,2,true);
assert.equal(results.confirmed.length,1);
assert.equal(results.unmatched.length,1);
assert.equal(results.snapshotOnly.length,1);
assert.equal(results.complete,true);
assert.equal(results.confirmed[0].title,'婚礼前夜');
assert.equal(reconcileRuntimeCatalog(base,[rows[0]],2,true).complete,false);
assert.equal(reconcileRuntimeCatalog([base[0],base[0]],rows,2,true).confirmed.length,0);
assert.equal(reconcileRuntimeCatalog(base,[rows[0],rows[0]],2,true).confirmed.length,0);
assert.equal(reconcileRuntimeCatalog(base,[{...rows[0],state_source:'isolated-test'}],1,true).confirmed.length,0);
assert.equal(reconcileRuntimeCatalog(base,[{...rows[0],episode_ref:'../unsafe'}],1,true).confirmed.length,0);
const monitor={
 available:true,database_identity_verified:true,read_only_grants_verified:true,
 task_records:[{status:'RUNNING'}],
 production_attempt_records:[{frame:7,status:'FAILED'}],
 generation_attempt_records:[{status:'OUTCOME_UNKNOWN'}]
};
const detail={mysql_monitor:monitor};
const summary=recordedTraceCoverage(detail);
assert.deepEqual({
 tasks:summary.taskCount,production:summary.productionAttemptCount,generation:summary.generationAttemptCount,
 unknown:summary.unresolvedCount,linked:summary.traceLinked,complete:summary.complete
},{tasks:1,production:1,generation:1,unknown:1,linked:false,complete:false});
assert.equal(recordedTraceCoverage({...detail,mysql_monitor:{...monitor,read_only_grants_verified:false}}).verified,false);
assert.equal(recordedTraceCoverage(null).taskCount,0);
console.log('R14_SOURCE_RECONCILIATION_AND_TRACE_GUARDS_11_PASS');
