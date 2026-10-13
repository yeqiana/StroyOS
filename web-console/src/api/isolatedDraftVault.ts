import type {LocalBackup} from './localDraftBackup';
type Envelope<T>={code:string;message?:string;data:T};
export type TestVaultItem={bundle_id:string;version:number;created_at:string};
async function call<T>(token:string,path:string,method:'GET'|'POST'='GET',body?:unknown):Promise<T>{
  if(token.trim().length<32)throw Error('隔离测试授权口令至少需要 32 个字符');
  const res=await fetch(path,{
    method,credentials:'same-origin',
    headers:{
      'Accept':'application/json',
      'Authorization':'Bearer '+token.trim(),
      ...(method==='POST'?{'Content-Type':'application/json','X-StoryOS-Draft-Intent':'confirmed'}:{})
    },
    body:body===undefined?undefined:JSON.stringify(body),
    cache:'no-store',
    signal:AbortSignal.timeout(8000)
  });
  const data=(await res.json()) as Envelope<T>;
  if(!res.ok||data.code!=='OK')throw Error(data.message||data.code||'隔离测试库不可用');
  return data.data;
}
export function saveTestBackup(token:string,backup:LocalBackup){
  return call<{bundle_id:string;version:number;production_created:false}>(token,'/api/v1/draft-vault','POST',{
    request_id:crypto.randomUUID(),backup
  });
}
export function listTestBackups(token:string){
  return call<{items:TestVaultItem[];test_only:true;production_created:false}>(token,'/api/v1/draft-vault');
}
export function getTestBackup(token:string,id:string){
  if(!/^TEST_BUNDLE_[a-f0-9-]{36}$/.test(id))throw Error('非法的测试存档 ID');
  return call<{backup:LocalBackup;test_only:true}>(token,'/api/v1/draft-vault/'+id);
}
