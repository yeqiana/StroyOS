import fs from 'node:fs';
import path from 'node:path';
// A WebCodex Runner may be a Windows service with a systemprofile LOCALAPPDATA.
export function resolveLocalPython({platform=process.platform,env=process.env,existsSync=fs.existsSync,readdirSync=fs.readdirSync,usersRoot='C:\\Users'}={}) {
  if(env.STORYOS_PYTHON?.trim()) return env.STORYOS_PYTHON.trim();
  if(platform!=='win32') return 'python3';
  const dirs=[env.LOCALAPPDATA, env.USERPROFILE ? path.win32.join(env.USERPROFILE,'AppData','Local') : null];
  try { for(const item of readdirSync(usersRoot,{withFileTypes:true})) {
    if(item.isDirectory()) dirs.push(path.win32.join(usersRoot,item.name,'AppData','Local'));
  } } catch { /* Explicit STORYOS_PYTHON remains available. */ }
  const matches=[...new Set(dirs.filter(Boolean).map(dir=>path.win32.join(dir,'Programs','Python','Python312','python.exe')))].filter(existsSync);
  if(matches.length===1) return matches[0];
  if(matches.length>1) throw Error('检测到多个 Python 安装，请通过 STORYOS_PYTHON 指定路径');
  throw Error('找不到 Python 3.12，请通过 STORYOS_PYTHON 指定只读 API 的 Python 路径');
}