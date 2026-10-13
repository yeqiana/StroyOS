/** Historical Run does not carry a trusted Episode ID; titles alone are ambiguous.
 * An exact single match is the only case where automatic navigation is safe.
 */
export function matchRunEpisodeByTitle<T extends {title:string}>(
  episodes: readonly T[], runTitle:string
): {kind:'unique'; episode:T} | {kind:'ambiguous' | 'missing'} {
  if (typeof runTitle !== 'string' || !runTitle.trim()) return {kind:'missing'};
  const found=episodes.filter(ep=>ep.title===runTitle);
  if (found.length===1) return {kind:'unique',episode:found[0]};
  return {kind:found.length?'ambiguous':'missing'};
}
