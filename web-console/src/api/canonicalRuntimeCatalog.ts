import {useCallback, useEffect, useState} from 'react';
import {platformApi} from './platformApi';

import {EMPTY,projectCanonicalCatalog,type CanonicalCatalogState} from './canonicalCatalogProjection';
export {projectCanonicalCatalog,matchCanonicalHistoricalEpisode} from './canonicalCatalogProjection';
let snapshot:CanonicalCatalogState|null=null;
let fetchedAt=0;
let pending:Promise<CanonicalCatalogState>|null=null;
const CACHE_MS=10000;

async function load():Promise<CanonicalCatalogState>{
  if(snapshot&&Date.now()-fetchedAt<CACHE_MS)return snapshot;
  if(!pending)pending=platformApi.runtimeStatuses(100,0)
    .then(data=>projectCanonicalCatalog(data))
    .catch(()=>({...EMPTY,status:'offline' as const,warning:'正式 Runtime 目录暂时不可读取；本地草稿仍保留'}))
    .then(value=>{snapshot=value;fetchedAt=Date.now();return value;})
    .finally(()=>{pending=null;});
  return pending;
}
export function useCanonicalRuntimeCatalog(){
  const [data,setData]=useState<CanonicalCatalogState>(()=>snapshot??EMPTY);
  const [revision,setRevision]=useState(0);
  useEffect(()=>{
    let active=true;
    void load().then(next=>{if(active)setData(next);});
    return()=>{active=false};
  },[revision]);
  const refresh=useCallback(()=>{snapshot=null;fetchedAt=0;setRevision(x=>x+1);},[]);
  return {...data,refresh};
}
