import React from 'react';
import {Drawer} from 'antd';
import type {Episode,ProjectItem} from '../types';

interface Props {
  projects:ProjectItem[];
  episodes:Episode[];
  onClose:()=>void;
  onOpenLibrary:()=>void;
  onSelectEpisode:(episode:Episode)=>void;
}
const CompactProjectsDrawer:React.FC<Props>=({projects,episodes,onClose,onOpenLibrary,onSelectEpisode})=>
  <Drawer open onClose={onClose} title="项目快捷访问" placement="left" width={340}>
    <div className="space-y-3">
      <button type="button" className="os-action w-full" onClick={()=>{onClose();onOpenLibrary();}}>查看全部作品与项目</button>
      {projects.map(project=><section key={project.id} className="border-b border-[var(--border-subtle)] pb-3">
        <h3 className="mb-2 flex items-center justify-between gap-3 text-[13px] font-semibold"><span className="truncate">{project.name}</span><span className="text-[12px] font-normal text-[var(--text-tertiary)]">{project.episodeIds.length}</span></h3>
        <div className="space-y-1">{episodes.filter(ep=>project.episodeIds.includes(ep.id)).map(ep=><button key={ep.id} type="button" onClick={()=>{onClose();onSelectEpisode(ep);}} className="block w-full truncate rounded-[5px] px-2 py-2 text-left text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]">{ep.title}</button>)}</div>
      </section>)}
    </div>
  </Drawer>;
export default CompactProjectsDrawer;
