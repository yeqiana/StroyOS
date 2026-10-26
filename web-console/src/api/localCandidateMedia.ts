import {useCallback,useEffect,useState} from 'react';

/** Local only: source files have NOT passed image review, and must never become publish assets. */
export interface CandidateEpisodeMedia {
  episode_ref: string;
  title: string;
  business_episode_id: string;
  source: 'local_workspace_unreviewed_candidates';
  candidate_count: number;
  preview: {frame:number;url:string;updated_at:string};
}
const LOCAL_MODE=import.meta.env.VITE_STORYOS_LOCAL_EVIDENCE_MODE==='true';
const REF=/^LOCAL_[a-f0-9]{24}$/;
const IMAGE=/^\/api\/v1\/local-media\/candidate-images\/[a-f0-9]{32}$/;

export function useLocalCandidateMedia() {
  const [items,setItems]=useState<CandidateEpisodeMedia[]>([]);
  useEffect(()=>{
    if(!LOCAL_MODE)return;
    let mounted=true;
    let busy=false;
    const refresh=async()=>{
      if(busy || !mounted)return;
      busy=true;
      try{
        const response=await fetch('/api/v1/local-media/candidates',{cache:'no-store',credentials:'same-origin'});
        if(!response.ok)throw Error('Candidate previews unavailable');
        const json=await response.json() as {code?:string;data?:{source?:string;items?:unknown[]}};
        if(json.code!=='OK'||json.data?.source!=='local_workspace_unreviewed_candidates'||!Array.isArray(json.data.items))
          throw Error('Invalid unreviewed-preview contract');
        const safe=json.data.items.flatMap((raw):CandidateEpisodeMedia[]=>{
          if(!raw||typeof raw!=='object')return [];
          const item=raw as Partial<CandidateEpisodeMedia>;
          if(!REF.test(item.episode_ref||'')||item.source!=='local_workspace_unreviewed_candidates'||
             typeof item.title!=='string'||!item.title||
             typeof item.business_episode_id!=='string'||!item.preview||
             !Number.isInteger(item.preview.frame)||item.preview.frame<1||item.preview.frame>99||
             !IMAGE.test(item.preview.url)||typeof item.preview.updated_at!=='string'||
             !Number.isInteger(item.candidate_count)||!Number.isFinite(item.candidate_count))return [];
          return [item as CandidateEpisodeMedia];
        });
        if(mounted)setItems(safe);
      }catch{
        // A missing preview source is never grounds for asserting production has stopped.
        if(mounted)setItems([]);
      }finally{busy=false;}
    };
    void refresh();
    const handle=window.setInterval(()=>{if(document.visibilityState!=='hidden')void refresh();},15000);
    return ()=>{mounted=false;window.clearInterval(handle);};
  },[]);
  const findByRuntimeRef=useCallback((ref:string)=>items.find(row=>row.episode_ref===ref),[items]);
  return {items,findByRuntimeRef};
}
