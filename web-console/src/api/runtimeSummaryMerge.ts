import type { RuntimeStatusSummary } from './platformApi';

/** Keep pagination stable across alias changes; names and titles are not identities. */
export function mergeRuntimeStatusSummaries(
  previous: RuntimeStatusSummary[], page: RuntimeStatusSummary[]
): RuntimeStatusSummary[] {
  const seen = new Set<string>();
  const merged: RuntimeStatusSummary[] = [];
  for (const item of [...previous, ...page]) {
    const identities = [item.episode_id, item.episode_ref, item.episode, item.business_episode_id]
      .filter((value): value is string => typeof value === 'string' && value.trim().length > 0);
    if (identities.some(id => seen.has(id))) continue;
    identities.forEach(id => seen.add(id));
    merged.push(item);
  }
  return merged;
}
