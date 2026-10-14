import React, {useEffect, useRef, useState} from 'react';
import {ClipboardCopy, Check, ChevronDown, ChevronUp, FilePenLine, ShieldCheck, Slash, Sparkles} from 'lucide-react';
import {DRAFT_SKILLS,matchDraftSkills} from '../utils/draftSkills';

interface CommandDockProps { onSendMessage: (text: string) => void; isLoading?: boolean; }
export const CommandDock: React.FC<CommandDockProps> = () => {
  const [draft,setDraft]=useState('');
  const [copied,setCopied]=useState(false);
  const [expanded,setExpanded]=useState(false);
  const [dismissed,setDismissed]=useState(false);
  const [activeIndex,setActiveIndex]=useState(0);
  const textareaRef=useRef<HTMLTextAreaElement>(null);
  const options=expanded&&!dismissed?matchDraftSkills(draft):[];
  const showSkills=options.length>0;
  const startSkill=()=>{
    setExpanded(true);setDraft('/');setDismissed(false);setActiveIndex(0);
    requestAnimationFrame(()=>textareaRef.current?.focus());
  };
  const selectSkill=(skill:typeof DRAFT_SKILLS[number])=>{
    setDraft(skill.template);setCopied(false);setDismissed(true);setActiveIndex(0);
    textareaRef.current?.focus();
  };
  useEffect(()=>{
    // Only intercept slash outside editable elements and active controls.
    const onKey=(event:KeyboardEvent)=>{
      if(event.key!=='/'||event.altKey||event.metaKey||event.ctrlKey||event.shiftKey||event.defaultPrevented)return;
      const el=event.target as HTMLElement|null;
      if(el?.closest('input,textarea,select,button,a,[role="button"],[role="combobox"],[contenteditable="true"]')||el?.isContentEditable)return;
      event.preventDefault();startSkill();
    };
    window.addEventListener('keydown',onKey);
    return()=>window.removeEventListener('keydown',onKey);
  },[]);
  const handleCopy=async()=>{
    if(!draft.trim())return;
    try{await navigator.clipboard.writeText(draft.trim());setCopied(true);}
    catch{setCopied(false);}
  };
  return <section aria-label="生产指令草稿" className="sticky bottom-0 z-20 w-full border-t border-[var(--border-subtle)] bg-[var(--bg-workspace)] px-4 py-2.5 text-[var(--text-primary)]">
    <div className="mx-auto w-full max-w-[1100px]">
      <div className="flex min-h-8 items-center justify-between gap-3">
        <button type="button" onClick={()=>setExpanded(v=>!v)} aria-expanded={expanded} aria-controls="storyos-command-panel" className="flex min-w-0 items-center gap-2 text-left text-[13px] font-semibold hover:text-[var(--info)]">
          <FilePenLine size={16} strokeWidth={1.75} className="shrink-0 text-[var(--text-secondary)]"/>
          生产指令草稿
          {expanded?<ChevronDown size={15}/>:<ChevronUp size={15}/>}
          {draft.trim()&&<span className="text-[11px] font-normal text-[var(--text-tertiary)]">已填写 · 未发送</span>}
        </button>
        <div className="flex shrink-0 items-center gap-2">
          <button type="button" onClick={startSkill} aria-label="打开斜杠快捷技能" className="inline-flex h-8 items-center gap-1.5 rounded-[4px] px-2 text-[12px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"><Slash size={14} strokeWidth={1.75}/>快捷技能</button>
          <span className="hidden text-[12px] text-[var(--text-tertiary)] sm:inline">仅本页草稿 · 不会触发任务</span>
        </div>
      </div>
      {expanded&&<div id="storyos-command-panel" className="mt-2 space-y-2 border-t border-[var(--border-subtle)] pt-3">
        <textarea ref={textareaRef} id="storyos-command-draft" aria-label="生产指令草稿内容" rows={3} value={draft}
          aria-controls={showSkills?'storyos-draft-skills':undefined} aria-expanded={showSkills}
          aria-activedescendant={showSkills?'storyos-draft-skill-'+options[activeIndex]?.id:undefined}
          onChange={e=>{setDraft(e.target.value);setCopied(false);setDismissed(false);setActiveIndex(0);}}
          onKeyDown={e=>{
            if(!showSkills)return;
            if(e.key==='ArrowDown'){e.preventDefault();setActiveIndex(index=>(index+1)%options.length);}
            if(e.key==='ArrowUp'){e.preventDefault();setActiveIndex(index=>(index+options.length-1)%options.length);}
            if(e.key==='Enter'){e.preventDefault();selectSkill(options[activeIndex]||options[0]);}
            if(e.key==='Escape'){e.preventDefault();setDismissed(true);}
          }}
          placeholder="记录制作意图、分镜修改建议或待执行任务… 输入 / 选择快捷技能"
          className="min-h-[82px] w-full resize-y rounded-[6px] border border-[var(--border-normal)] bg-[var(--bg-surface)] px-3 py-2.5 text-[13px] text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] focus-visible:border-[var(--focus)]"/>
        {showSkills&&<div id="storyos-draft-skills" role="listbox" aria-label="创作快捷技能" className="overflow-hidden rounded-[6px] border border-[var(--border-normal)] bg-[var(--bg-elevated)]">
          {options.map((skill,index)=><button key={skill.id} id={'storyos-draft-skill-'+skill.id} role="option" aria-selected={activeIndex===index} type="button"
            onMouseEnter={()=>setActiveIndex(index)} onClick={()=>selectSkill(skill)}
            className={'flex min-h-9 w-full items-center gap-3 border-b border-[var(--border-subtle)] px-3 py-2 text-left last:border-b-0 hover:bg-[var(--bg-hover)] '+(activeIndex===index?'bg-[var(--bg-selected)]':'')}>
            <Sparkles size={14} strokeWidth={1.75} className="shrink-0 text-[var(--text-secondary)]"/>
            <span className="w-16 shrink-0 text-[12px] font-semibold">{skill.command}</span>
            <span className="min-w-0 truncate text-[12px] text-[var(--text-secondary)]">{skill.description}</span>
          </button>)}
          <p className="px-3 py-1.5 text-[11px] text-[var(--text-tertiary)]">↑↓ 选择 · Enter 插入草稿 · Esc 关闭 · 不执行生产</p>
        </div>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[12px] text-[var(--text-tertiary)]"><ShieldCheck size={14}/>尚未连接生产写入接口，草稿仅在当前页面暂存</span>
          <button type="button" disabled={!draft.trim()} onClick={handleCopy} className="os-action os-action-primary disabled:cursor-not-allowed disabled:opacity-40">
            {copied?<Check size={14}/>:<ClipboardCopy size={14}/>} {copied?'已复制':'复制草稿'}
          </button>
        </div>
      </div>}
    </div>
  </section>;
};