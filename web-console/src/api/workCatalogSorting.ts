/** Explicit evidence-aware ordering for the unified Works catalog. */
export type WorkSortKey = 'updated' | 'status' | 'completion';
export type WorkSortDirection = 'asc' | 'desc';
export interface SortableWork {
  key: string;
  updated: string;
  statusRank: number | null;
  completionPercent: number | null;
}
const timestamp=(raw:string):number|null=>{
  const time=Date.parse(raw);
  return Number.isFinite(time)?time:null;
};
export function sortWorks<T extends SortableWork>(rows:readonly T[],key:WorkSortKey,direction:WorkSortDirection):T[] {
  const scale=direction==='asc'?1:-1;
  return [...rows].sort((a,b)=>{
    const av=key==='updated'?timestamp(a.updated):key==='status'?a.statusRank:a.completionPercent;
    const bv=key==='updated'?timestamp(b.updated):key==='status'?b.statusRank:b.completionPercent;
    if(av===null && bv===null)return a.key.localeCompare(b.key);
    if(av===null)return 1; // Unknowns always after verified values.
    if(bv===null)return -1;
    return av!==bv?(av-bv)*scale:a.key.localeCompare(b.key);
  });
}
export function galleryColumns(viewportWidth:number):number {
  if(viewportWidth>=1280)return 4;
  if(viewportWidth>=1024)return 3;
  if(viewportWidth>=640)return 2;
  return 1;
}
export function galleryPageCapacity(viewportWidth:number,rowsPerPage:number=3):number {
  const rowCount=Number.isInteger(rowsPerPage)?Math.max(2,Math.min(6,rowsPerPage)):3;
  return galleryColumns(viewportWidth)*rowCount;
}
