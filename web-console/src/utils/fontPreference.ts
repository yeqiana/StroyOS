export type FontPreference = 'balanced' | 'chinese';
export type PreferencePersistence = 'default' | 'saved' | 'session-only';

const KEY = 'storyos:font-preference:v1';
const isFontPreference = (value: unknown): value is FontPreference => value === 'balanced' || value === 'chinese';

export function loadFontPreference(): {value: FontPreference; persistence: PreferencePersistence} {
  try {
    const saved = localStorage.getItem(KEY);
    if (isFontPreference(saved)) return {value:saved,persistence:'saved'};
  } catch { return {value:'balanced',persistence:'session-only'}; }
  return {value:'balanced',persistence:'default'};
}

export function saveFontPreference(value: FontPreference): PreferencePersistence {
  if (!isFontPreference(value)) return 'session-only';
  try {
    localStorage.setItem(KEY,value);
    return localStorage.getItem(KEY) === value ? 'saved' : 'session-only';
  } catch { return 'session-only'; }
}
