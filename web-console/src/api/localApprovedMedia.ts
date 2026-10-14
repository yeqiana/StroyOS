import {useCallback,useEffect,useState} from 'react';

/** Read-only local media projection. Never accepts or constructs filesystem paths. */
export interface ApprovedFrame { frame:number; url:string }
export interface ApprovedEpisodeMedia {
  title:string;
  business_episode_id:string;
  episode_ref:string;
  source:'local_workspace_approved_only';
  frames:ApprovedFrame[];
}
const LOCAL_MODE=import.meta.env.VITE_STORYOS_LOCAL_EVIDENCE_MODE==='true';
const SAFE_URL=/^\/api\/v1\/local-media\/images\/[a-f0-9]{32}$/;
let cached:ApprovedEpisodeMedia[]|null=null;
let pending:Promise<ApprovedEpisodeMedia[]>|null=null;

async function getCatalog():Promise<ApprovedEpisodeMedia[]> {
  if(!LOCAL_MODE)return [];
  if(cached)return cached;
  if(!pending)pending=fetch('/api/v1/local-media/catalog',{credentials:'same-origin',cache:'no-store'})
    .then(async response=>{
      if(!response.ok)throw Error('Approved media unavailable');
      const json=await response.json() as {code?:string;data?:{source?:string;items?:unknown[]}};
      if(json.code!=='OK'||json.data?.source!=='local_workspace_approved_only'||!Array.isArray(json.data.items))throw Error('Invalid approved-media contract');
      return json.data.items.flatMap(raw=>{
        if(!raw||typeof raw!=='object')return [];
        const a=raw as Partial<ApprovedEpisodeMedia>;
        if(typeof a.title!=='string'||!a.title||typeof a.business_episode_id!=='string'||!Array.isArray(a.frames)||a.source!=='local_workspace_approved_only')return [];
        const frames=a.frames.filter((f):f is ApprovedFrame=>Boolean(f&&Number.isInteger(f.frame)&&f.frame>=1&&f.frame<=20&&typeof f.url==='string'&&SAFE_URL.test(f.url)));
        if(!frames.length)return [];
        return [{title:a.title,business_episode_id:a.business_episode_id,episode_ref:typeof a.episode_ref==='string'?a.episode_ref:'',source:'local_workspace_approved_only' as const,frames}];
      });
    }).then(items=>(cached=items)).finally(()=>{pending=null;});
  return pending;
}

export function useLocalApprovedMedia() {
  const [items,setItems]=useState<ApprovedEpisodeMedia[]>(()=>cached??[]);
  useEffect(()=>{
    if(!LOCAL_MODE)return;
    let active=true;
    void getCatalog().then(result=>{if(active)setItems(result);}).catch(()=>{if(active)setItems([]);});
    return ()=>{active=false;};
  },[]);
  const findEpisode=useCallback((title:string,code?:string)=>{
    if(!LOCAL_MODE)return undefined;
    const matches=items.filter(ep=>ep.title===title&&(!code||ep.business_episode_id===code));
    if(matches.length===1)return matches[0];
    // Some legacy index rows use the full Chinese title as their code, not a business ID.
    // In that one case allow an exact-title alias only if the local approved catalog has
    // exactly one owner; never fall back when a real business ID mismatches or is ambiguous.
    if(matches.length || !code || code!==title)return undefined;
    const uniqueOwner=items.filter(ep=>ep.title===title);
    return uniqueOwner.length===1?uniqueOwner[0]:undefined;
  },[items]);
  return {findEpisode, localMode:LOCAL_MODE};
}

/** Verifies currently served approved-source bytes only, not a production binding. */
export interface ApprovedSourceFingerprint {
  source:'local_workspace_approved_only';
  episode_ref:string;
  frame:number;
  url:string;
  sha256:string;
  evidence_kind:'LOCAL_APPROVED_SOURCE_BYTES';
  production_reference_binding:'NOT_SUBMITTED';
  provider_execution:'UNVERIFIED';
}
const LOCAL_REF=/^LOCAL_[a-f0-9]{24}$/;
const SHA256=/^[a-f0-9]{64}$/;
export async function fetchApprovedSourceFingerprint(episodeRef:string,url:string):Promise<ApprovedSourceFingerprint> {
  if(!LOCAL_MODE||!LOCAL_REF.test(episodeRef)||!SAFE_URL.test(url))throw Error('APPROVED_SOURCE_IDENTITY_INVALID');
  const token=url.slice(url.lastIndexOf('/')+1);
  const resp=await fetch('/api/v1/local-media/source-fingerprint/'+episodeRef+'/'+token,{
    credentials:'same-origin',cache:'no-store',
  });
  if(!resp.ok)throw Error('APPROVED_SOURCE_NOT_VERIFIABLE');
  const json=await resp.json() as {code?:string;data?:Partial<ApprovedSourceFingerprint>};
  const p=json.data;
  if(json.code!=='OK'||!p||p.episode_ref!==episodeRef||p.url!==url
    ||p.source!=='local_workspace_approved_only'||p.evidence_kind!=='LOCAL_APPROVED_SOURCE_BYTES'
    ||p.production_reference_binding!=='NOT_SUBMITTED'||p.provider_execution!=='UNVERIFIED'
    ||!Number.isInteger(p.frame)||p.frame < 1||p.frame > 20||typeof p.sha256!=='string'||!SHA256.test(p.sha256)){
    throw Error('APPROVED_SOURCE_EVIDENCE_INVALID');
  }
  return p as ApprovedSourceFingerprint;
}
