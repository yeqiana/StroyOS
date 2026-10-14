/** UI planning only: never a production frame-reference binding. */
export type LocalReferenceDraft = Record<number, {sourceFrame: number; sourceUrl: string}>;
const IMAGE_URL = /^\/api\/v1\/local-media\/images\/[a-f0-9]{32}$/;
const keyFor = (episodeId: string) => 'storyos:reference-draft:v1:' + episodeId;

export function loadLocalReferenceDraft(episodeId: string): LocalReferenceDraft {
  try {
    const raw = JSON.parse(window.localStorage.getItem(keyFor(episodeId)) || "{}") as unknown;
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    const valid: LocalReferenceDraft = {};
    for (const [target, reference] of Object.entries(raw)) {
      const frame = Number(target);
      if (!Number.isInteger(frame) || frame < 1 || frame > 20 || !reference || typeof reference !== 'object') continue;
      const item = reference as {sourceFrame?: unknown; sourceUrl?: unknown};
      if (typeof item.sourceFrame !== 'number' || !Number.isInteger(item.sourceFrame) || item.sourceFrame < 1 || item.sourceFrame > 20 || item.sourceFrame === frame) continue;
      if (typeof item.sourceUrl !== 'string' || !IMAGE_URL.test(item.sourceUrl)) continue;
      valid[frame] = {sourceFrame: item.sourceFrame, sourceUrl: item.sourceUrl};
    }
    return valid;
  } catch { return {}; }
}

export function saveLocalReferenceDraft(episodeId: string, draft: LocalReferenceDraft): boolean {
  try {
    if (Object.keys(draft).length) window.localStorage.setItem(keyFor(episodeId), JSON.stringify(draft));
    else window.localStorage.removeItem(keyFor(episodeId));
    return true;
  } catch { return false; }
}

export function referenceDraftKey(episodeId: string): string { return keyFor(episodeId); }
