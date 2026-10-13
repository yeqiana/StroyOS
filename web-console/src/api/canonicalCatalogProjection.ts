import type {Episode} from '../types';
import type {RuntimeStatusList,RuntimeStatusSummary} from './platformApi';

export type CanonicalCatalogState = {
  items: RuntimeStatusSummary[];
  status: 'loading'|'complete'|'partial'|'offline';
  total: number | null;
  warning: string|null;
};

export const EMPTY:CanonicalCatalogState={items:[],status:'loading',total:null,warning:null};
const EPISODE_REF=/^LOCAL_[a-f0-9]{24}$/;

/** The actual read-only local Runtime catalog, NOT the historic TS snapshot.
 * Rejects fixture rows and duplicate/invalid identities; never maps via title.
 */
export function projectCanonicalCatalog(data: RuntimeStatusList):CanonicalCatalogState {
  if(!data||!Array.isArray(data.items)||!Number.isSafeInteger(data.total)||data.total<0)
    return {...EMPTY,status:'partial',warning:'正式目录响应结构无法核验'};
  const seen=new Set<string>();
  const items:RuntimeStatusSummary[]=[];
  let rejected=0;
  for(const row of data.items){
    if(!row||row.state_source!=='local_workspace_episode_state_file'
      ||typeof row.episode_ref!=='string'||!EPISODE_REF.test(row.episode_ref)
      ||typeof row.business_episode_id!=='string'||!row.business_episode_id.trim()
      ||typeof row.title!=='string'||!row.title.trim()||seen.has(row.episode_ref)){
      rejected++;continue;
    }
    seen.add(row.episode_ref);
    items.push(row);
  }
  const complete=Boolean(!rejected&&!data.has_more&&!data.errors?.length
    &&data.total===data.items.length&&data.count===data.items.length);
  return {
    items,status:complete?'complete':'partial',total:data.total,
    warning:complete?null:'只显示已核验的正式作品，部分记录缺失或来源无法核验',
  };
}

/** A historic episode can be opened only after a unique ID+title agreement. */
export function matchCanonicalHistoricalEpisode(
  official:RuntimeStatusSummary, indexed:ReadonlyArray<Episode>,
  real:ReadonlyArray<RuntimeStatusSummary>,
):Episode|null {
  if(!official.episode_ref||!EPISODE_REF.test(official.episode_ref)||!official.business_episode_id||!official.title)return null;
  if(real.filter(r=>r.episode_ref===official.episode_ref).length!==1)return null;
  if(real.filter(r=>r.business_episode_id===official.business_episode_id&&r.title===official.title).length!==1)return null;
  const found=indexed.filter(ep=>!/^ep-(home|proj)-/.test(ep.id)
    &&ep.code===official.business_episode_id&&ep.title===official.title);
  return found.length===1?found[0]:null;
}
