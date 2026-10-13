import type {Episode, ProjectItem} from '../types';

export const BACKUP_FORMAT='storyos-local-draft-backup';
export const BACKUP_VERSION=1;
export const MAX_BACKUP_CHARS=2_000_000;
// Default projects are preloaded on a fresh browser; backing them up as new
// projects would always collide on cross-device restore.
const DEFAULT_PROJECT_IDS=new Set(['proj-aigc-dali','proj-storyos','proj-urban','proj-relic']);
const isDraft=(x:unknown):x is Episode=>{
  if(!x||typeof x!=='object'||Array.isArray(x))return false;
  const v=x as Partial<Episode>;
  return typeof v.id==='string' && /^ep-(home|proj)-[a-zA-Z0-9_-]{1,70}$/.test(v.id)
    && typeof v.title==='string' && v.title.length>=1 && v.title.length<=220
    && typeof v.code==='string' && typeof v.synopsis==='string'
    && Array.isArray(v.frameReviews) && Array.isArray(v.preflightChecks)
    && Array.isArray(v.storyboardBeats) && Array.isArray(v.characters)
    && v.runtimeRequest!==null && typeof v.runtimeRequest==='object'
    && typeof v.currentStage==='string';
};
const isProject=(x:unknown):x is ProjectItem=>{
  if(!x||typeof x!=='object'||Array.isArray(x))return false;
  const v=x as Partial<ProjectItem>;
  return typeof v.id==='string'&&/^proj-[a-zA-Z0-9_-]{1,70}$/.test(v.id)
    &&typeof v.name==='string'&&v.name.length>=1&&v.name.length<=220
    &&typeof v.createdAt==='string'&&Array.isArray(v.episodeIds)
    &&v.episodeIds.length<=200
    &&v.episodeIds.every(id=>typeof id==='string'&&id.length<150);
};
export type LocalBackup={format:typeof BACKUP_FORMAT;version:1;exportedAt:string;source:'browser_local_only';drafts:Episode[];projects:ProjectItem[]};
export function createDraftBackup(episodes:readonly Episode[], projects:readonly ProjectItem[]):LocalBackup {
  return {format:BACKUP_FORMAT,version:1,exportedAt:new Date().toISOString(),
    source:'browser_local_only',drafts:episodes.filter(isDraft),
    projects:projects.filter(isProject).filter(p=>!DEFAULT_PROJECT_IDS.has(p.id))};
}
export type RestoreResult={
  ok:boolean;reason:string;addedDrafts:Episode[];addedProjects:ProjectItem[];
  draftCount:number;projectCount:number;
};
const fail=(reason:string):RestoreResult=>({ok:false,reason,addedDrafts:[],addedProjects:[],draftCount:0,projectCount:0});
/** Validate fully before touching React state/localStorage; no overwrite ever.
 * A colliding ID, even with the same title, requires manual review.
 */
export function reviewDraftRestore(
  text:string,existingEpisodes:readonly Episode[],existingProjects:readonly ProjectItem[],
):RestoreResult {
  if(typeof text!=='string'||text.length>MAX_BACKUP_CHARS||text.length<20)
    return fail('备份文件超过 2MB 或格式无效');
  let raw:unknown;
  try{raw=JSON.parse(text)}catch{return fail('不是有效的 JSON 备份')}
  if(!raw||typeof raw!=='object'||Array.isArray(raw))return fail('备份根结构错误');
  const v=raw as Partial<LocalBackup>;
  if(v.format!==BACKUP_FORMAT||v.version!==BACKUP_VERSION||v.source!=='browser_local_only'
    ||!Array.isArray(v.drafts)||!Array.isArray(v.projects)
    ||v.drafts.length>100||v.projects.length>100
    ||!v.drafts.every(isDraft)||!v.projects.every(isProject))
    return fail('备份版本、作品结构或项目结构未通过安全校验');
  const draftIds=v.drafts.map(x=>x.id),projectIds=v.projects.map(x=>x.id);
  if(new Set(draftIds).size!==draftIds.length||new Set(projectIds).size!==projectIds.length)
    return fail('备份中存在重复草稿或项目 ID');
  const usedEpisodes=new Set(existingEpisodes.map(x=>x.id));
  const usedProjects=new Set(existingProjects.map(x=>x.id));
  if(draftIds.some(id=>usedEpisodes.has(id))||projectIds.some(id=>usedProjects.has(id)))
    return fail('现有数据存在相同 ID：已拒绝覆盖，请在独立浏览器中人工核对');
  const referenced=new Set([...projectIds,...existingProjects.map(p=>p.id)]);
  if(v.drafts.some(x=>x.projectId&&!referenced.has(x.projectId)))
    return fail('草稿引用了不存在的项目，未导入');
  return {ok:true,reason:'等待确认导入（不会创建正式 Runtime 作品）',
    addedDrafts:v.drafts,addedProjects:v.projects,draftCount:v.drafts.length,projectCount:v.projects.length};
}
