import type {LocalBackup} from './localDraftBackup';

type ApiResult<T>={code:string;data:T;message?:string};
type WebSession={session_token:string;csrf_token:string;scope:'web_drafts:draft_only';draft_only:true};
export type WebDraftSummary={workspace_id:string;version:number;updated_at:string};
export type SavedWebDraft={workspace_id:string;version:number;identity_map:{
 projects:Record<string,string>;drafts:Record<string,string>};
 canonical_episode_created:false;production_started:false};

async function parse<T>(response:Response):Promise<T>{
 const value=await response.json() as ApiResult<T>;
 if(!response.ok||value.code!=='OK')throw Error(value.message||value.code||'服务端草稿不可用');
 return value.data;
}
async function authorized<T>(secret:string,action:(session:WebSession)=>Promise<T>):Promise<T>{
 if(secret.trim().length<32)throw Error('草稿操作口令至少需要 32 字符');
 const session=await parse<WebSession>(await fetch('/api/v1/web-drafts/session',{
   method:'POST',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000),
   headers:{Authorization:'Bearer '+secret.trim(),'X-StoryOS-Draft-Intent':'confirmed'}
 }));
 if(session.scope!=='web_drafts:draft_only'||!session.draft_only)throw Error('草稿操作权限不匹配');
 try{return await action(session);}
 finally{
  try{await fetch('/api/v1/web-drafts/session',{method:'DELETE',
   credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(2500),
   headers:{Authorization:'Bearer '+session.session_token,'X-StoryOS-Draft-Intent':'confirmed',
   'X-StoryOS-CSRF':session.csrf_token}});}catch{/* expires after 15 min */}
 }
}
async function call<T>(session:WebSession,path:string,method:'GET'|'POST'|'PUT'='GET',payload?:unknown):Promise<T>{
 const write=method!=='GET';
 return parse<T>(await fetch(path,{
  method,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(15000),
  headers:{Authorization:'Bearer '+session.session_token,Accept:'application/json',
   ...(write?{'Content-Type':'application/json','X-StoryOS-Draft-Intent':'confirmed',
   'X-StoryOS-CSRF':session.csrf_token}:{})},
  body:payload?JSON.stringify(payload):undefined
 }));
}
export function saveWebDraft(token:string,backup:LocalBackup,current?:{workspace_id:string;version:number}){
 if(current&&!/^WDW_[a-f0-9-]{36}$/.test(current.workspace_id))throw Error('无效的草稿工作区 ID');
 return authorized(token,session=>call<SavedWebDraft>(session,
  '/api/v1/web-drafts'+(current?'/'+current.workspace_id:''),
  current?'PUT':'POST',{request_id:crypto.randomUUID(),backup,
   ...(current?{expected_version:current.version}:{})}));
}
export function listWebDrafts(token:string){
 return authorized(token,session=>call<{items:WebDraftSummary[];production_started:false}>(session,'/api/v1/web-drafts'));
}
export function readWebDraft(token:string,id:string){
 if(!/^WDW_[a-f0-9-]{36}$/.test(id))throw Error('无效的草稿工作区 ID');
 return authorized(token,session=>call<{workspace_id:string;version:number;backup:LocalBackup;
 identity_map:SavedWebDraft['identity_map'];canonical_episode_created:false}>(session,
 '/api/v1/web-drafts/'+id));
}
export type HandoffItem={
 server_draft_id:string;source_draft_id:string;title:string;
 preflight_available:boolean;reason:string|null;preflight_argv?:string[];
 canonical_episode_created:false;production_started:false;
};
export type HandoffPlan={
 workspace_id:string;workspace_version:number;source_sha256:string;
 authority:'READ_ONLY_HANDOFF_PLAN';requires_human_approval:true;
 admission_granted:false;canonical_episode_created:false;production_started:false;
 model_calls:0;runtime_writes:0;items:HandoffItem[];
};
/** Inspect saved server bytes only; never creates an Episode or starts a Driver. */
export function inspectWebDraftHandoff(token:string,id:string){
 if(!/^WDW_[a-f0-9-]{36}$/.test(id))throw Error('无效的草稿工作区 ID');
 return authorized(token,session=>call<HandoffPlan>(
  session,'/api/v1/web-drafts/'+id+'/handoff-plan'));
}
