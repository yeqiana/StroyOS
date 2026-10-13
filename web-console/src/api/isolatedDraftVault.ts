import type {LocalBackup} from './localDraftBackup';
type Envelope<T>={code:string;message?:string;data:T};
export type TestVaultItem={bundle_id:string;version:number;created_at:string};
type VaultSession={session_token:string;csrf_token:string;expires_at:number;backend:'sqlite_test_only'|'mysql8_test_only';scope:'draft_vault:test_only';test_only:true};
async function parse<T>(response:Response):Promise<T>{
 const result=await response.json() as Envelope<T>;
 if(!response.ok||result.code!=='OK')throw Error(result.message||result.code||'隔离草稿库请求失败');
 return result.data;
}
async function withSession<T>(token:string,action:(session:VaultSession)=>Promise<T>):Promise<T>{
 if(token.trim().length<32)throw Error('隔离测试授权口令至少 32 字符');
 const login=await fetch('/api/v1/draft-vault/session',{
  method:'POST',credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000),
  headers:{Authorization:'Bearer '+token.trim(),'X-StoryOS-Draft-Intent':'confirmed'}
 });
 const session=await parse<VaultSession>(login);
 if(!session.test_only||session.scope!=='draft_vault:test_only')throw Error('非隔离操作会话已拒绝');
 try{return await action(session);}
 finally{
  // Voluntary immediate revocation even though server also expires sessions.
  try{await fetch('/api/v1/draft-vault/session',{method:'DELETE',
   credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(3000),
   headers:{Authorization:'Bearer '+session.session_token,
    'X-StoryOS-Draft-Intent':'confirmed','X-StoryOS-CSRF':session.csrf_token}
  });}catch{/* expires server-side within 15 minutes */}
 }
}
async function call<T>(session:VaultSession,path:string,method:'GET'|'POST'|'PUT'='GET',body?:unknown):Promise<T>{
 const mutation=method!=='GET';
 const res=await fetch(path,{
  method,credentials:'same-origin',
  headers:{
   Accept:'application/json',
   Authorization:'Bearer '+session.session_token,
   ...(mutation?{'Content-Type':'application/json','X-StoryOS-Draft-Intent':'confirmed',
     'X-StoryOS-CSRF':session.csrf_token}:{})
  },
  body:body===undefined?undefined:JSON.stringify(body),
  cache:'no-store',signal:AbortSignal.timeout(15000)
 });
 return parse<T>(res);
}
export function saveTestBackup(token:string,backup:LocalBackup){
 return withSession(token,async session=>{
  const response=await call<{bundle_id:string;version:number;production_created:false}>(session,
   '/api/v1/draft-vault','POST',{request_id:crypto.randomUUID(),backup});
  return {...response,backend:session.backend};
 });
}
export function listTestBackups(token:string){
 return withSession(token,session=>call<{items:TestVaultItem[];test_only:true;production_created:false;backend:string}>(session,
  '/api/v1/draft-vault'));
}
export function getTestBackup(token:string,id:string){
 if(!/^TEST_BUNDLE_[a-f0-9-]{36}$/.test(id))throw Error('非法的测试存档 ID');
 return withSession(token,session=>call<{backup:LocalBackup;test_only:true}>(session,
  '/api/v1/draft-vault/'+id));
}
export type SavedWorkspaceItem={workspace_id:string;version:number;updated_at:string};
export function saveWorkspace(token:string,backup:LocalBackup,current?:{workspace_id:string;version:number}){
 return withSession(token,session=>call<{workspace_id:string;version:number;test_only:true;production_created:false}>(
  session,current?'/api/v1/draft-vault/workspaces/'+current.workspace_id:'/api/v1/draft-vault/workspaces',
  current?'PUT':'POST',{
   request_id:crypto.randomUUID(),backup,...(current?{expected_version:current.version}:{})
  }));
}
export function listWorkspaces(token:string){
 return withSession(token,session=>call<{items:SavedWorkspaceItem[];test_only:true}>(session,
  '/api/v1/draft-vault/workspaces'));
}
export function getWorkspace(token:string,id:string){
 if(!/^TEST_WORKSPACE_[a-f0-9-]{36}$/.test(id))throw Error('工作区 ID 无效');
 return withSession(token,session=>call<{backup:LocalBackup;version:number;test_only:true}>(session,
  '/api/v1/draft-vault/workspaces/'+id));
}
