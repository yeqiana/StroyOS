import type { Episode } from '../types';
import type { RuntimeStatusSummary } from './platformApi';

/** Only exact, unique business episode ID AND title can bind two projections.
 * A name-only match is intentionally insufficient (renames and duplicates).
 */
export function reconcileRuntimeCatalog(
  indexed: ReadonlyArray<Pick<Episode,'id'|'code'|'title'>>,
  rows: ReadonlyArray<RuntimeStatusSummary>,
  total: number | null,
  sourceComplete: boolean,
) {
  const existing = indexed.filter(ep=>!/^ep-(home|proj)-/.test(ep.id));
  const authoritative = rows.filter(x=>x.state_source==='local_workspace_episode_state_file'
    && typeof x.business_episode_id==='string' && typeof x.title==='string'
    && /^LOCAL_[a-f0-9]{24}$/.test(x.episode_ref||''));
  const matchKey=(code:string,title:string)=>JSON.stringify([code,title]);
  const unique = (keys:string[]) => new Map(keys.map(k=>[k,keys.filter(x=>x===k).length]));
  const oldCounts=unique(existing.map(ep=>matchKey(ep.code,ep.title)));
  const realCounts=unique(authoritative.map(x=>matchKey(x.business_episode_id!,x.title!)));
  const confirmed=authoritative.filter(x=>{
    const key=matchKey(x.business_episode_id!,x.title!);
    return oldCounts.get(key)===1 && realCounts.get(key)===1;
  });
  const unmatched=authoritative.filter(x=>!confirmed.includes(x));
  const snapshotOnly=existing.filter(ep=>{
    const key=matchKey(ep.code,ep.title);
    return oldCounts.get(key)!==1 || realCounts.get(key)!==1;
  });
  const complete=sourceComplete && typeof total==='number' && total===rows.length
    && authoritative.length===rows.length;
  return {confirmed,unmatched,snapshotOnly,observed:authoritative.length,complete};
}
