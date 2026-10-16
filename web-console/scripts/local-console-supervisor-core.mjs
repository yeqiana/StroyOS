export function nextHealthMisses(previous,healthy){return healthy?0:previous+1}
export function restartWindow(previous,now,windowMs=600000,maxRestarts=3){
 const recent=previous.filter(t=>t>=now-windowMs);
 return {allowed:recent.length<maxRestarts,history:recent};
}