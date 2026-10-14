import type {FrameReviewResult} from '../types';

export type ConsistencyCategory='character'|'style'|'scene';
export const CONSISTENCY_CATEGORIES = [
  {id:'character',label:'人物与角色',pattern:/(角色|人物|面容|面部|五官|发型|服装|人脸|facial|face|character|costume)/i},
  {id:'style',label:'画风与光影',pattern:/(画风|风格|光影|光线|光照|色调|色彩|色温|style|lighting|color|colour)/i},
  {id:'scene',label:'场景与环境',pattern:/(场景|背景|环境|空间|地理|布景|scene|background|environment)/i}
] as const;

/** This is text-tag navigation, not a model assessment or similarity score. */
export function summarizeConsistency(reviews:readonly FrameReviewResult[], frameLimit=20) {
  const unique = new Map<number,FrameReviewResult>();
  for(const review of reviews) if(Number.isInteger(review.frameIndex)&&review.frameIndex>=1&&review.frameIndex<=frameLimit) unique.set(review.frameIndex,review);
  const relevant=[...unique.values()];
  const alerts=relevant.filter(review=>review.verdict==='WARN'||review.verdict==='FAIL');
  const categories=CONSISTENCY_CATEGORIES.map(category=>({
    id:category.id as ConsistencyCategory,label:category.label,
    frames:alerts.filter(review=>review.issueTags?.some(tag=>category.pattern.test(tag))).map(review=>review.frameIndex).sort((a,b)=>a-b)
  }));
  const classified = new Set(categories.flatMap(category=>category.frames));
  const unclassified=alerts.filter(review=>!classified.has(review.frameIndex)).map(review=>review.frameIndex).sort((a,b)=>a-b);
  return {reviewed:relevant.length,unreviewed:Math.max(0,frameLimit-relevant.length),alerts:alerts.length,categories,unclassified};
}
