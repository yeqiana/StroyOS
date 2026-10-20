import type { Episode } from '../types';

export type DraftProfile = { title: string; synopsis: string; genre: string };
export const isManagedDraft = (value: Pick<Episode,'id'>) => /^ep-(home|proj)-[A-Za-z0-9_-]+$/.test(value.id);
export function validateDraftProfile(value: DraftProfile): DraftProfile {
  const title = value.title.trim(), synopsis = value.synopsis.trim(), genre = value.genre.trim();
  if (title.length < 1 || title.length > 100) throw new Error('作品名称必须为 1–100 字');
  if (synopsis.length > 2000) throw new Error('剧情简介最多 2000 字');
  if (genre.length < 1 || genre.length > 40) throw new Error('类型必须为 1–40 字');
  return {title, synopsis, genre};
}
export function editLocalDraft(episodes: Episode[], id: string, input: DraftProfile, now: string): Episode[] {
  const data = validateDraftProfile(input);
  const selected = episodes.find(ep=>ep.id===id);
  if (!selected || !isManagedDraft(selected)) throw new Error('仅允许修改本机草稿，不得改动正式生产作品');
  return episodes.map(ep=>ep.id===id ? {...ep, ...data, updatedAt:now} : ep);
}
export function removeLocalDraft(episodes: Episode[], id: string): Episode[] {
  const selected = episodes.find(ep=>ep.id===id);
  if (!selected || !isManagedDraft(selected)) throw new Error('仅允许删除本机草稿，不得删除正式生产作品');
  return episodes.filter(ep=>ep.id!==id);
}
