import React, {useRef, useState} from 'react';
import {Button, Modal, Input, Select} from 'antd';
import {saveTestBackup,listTestBackups,getTestBackup} from '../../api/isolatedDraftVault';
import type {Episode,ProjectItem} from '../../types';
import {createDraftBackup,MAX_BACKUP_CHARS,reviewDraftRestore} from '../../api/localDraftBackup';

type Props={
  episodes:Episode[];projects:ProjectItem[];
  onRestore:(json:string)=>void;
};
export const LocalDraftSafetyPanel:React.FC<Props>=({episodes,projects,onRestore})=>{
  const fileRef=useRef<HTMLInputElement>(null);
  const [status,setStatus]=useState<string|null>(null);
  const [operatorToken,setOperatorToken]=useState('');
  const [testBusy,setTestBusy]=useState(false);
  const [vaultItems,setVaultItems]=useState<Array<{bundle_id:string;created_at:string}>>([]);
  const [selectedVaultId,setSelectedVaultId]=useState<string|undefined>();
  const drafts=episodes.filter(x=>/^ep-(home|proj)-/.test(x.id));

  // Isolated SQLite test vault only; never creates a canonical Project/Episode.
  const saveTestOnly=()=>{
    Modal.confirm({
      title:'保存到 R17 隔离测试存档？',
      content:'仅向 TEST_ONLY 本地测试数据库写入一份草稿副本。不会创建正式作品、连接生产 MySQL 或执行图片生成。',
      okText:'确认测试存档',cancelText:'取消',
      onOk:async()=>{
        setTestBusy(true);
        try {
          const value=await saveTestBackup(operatorToken,createDraftBackup(episodes,projects));
          setStatus('已保存 '+value.backend+' 隔离存档 '+value.bundle_id+'；没有创建正式 Runtime 作品。');
        }catch(e){setStatus('隔离存档失败：'+(e instanceof Error?e.message:'未知错误'));}
        finally{setTestBusy(false);}
      }
    });
  };
  const reviewVaultList=async()=>{
    setTestBusy(true);
    try {const catalog=await listTestBackups(operatorToken);setVaultItems(catalog.items);
      setSelectedVaultId(catalog.items[0]?.bundle_id);
      setStatus('隔离存档 '+catalog.items.length+' 份 · '+catalog.backend+' · 正式 Runtime 未变化');
    }catch(e){setStatus('查询隔离存档失败：'+(e instanceof Error?e.message:'未知错误'));}
    finally{setTestBusy(false);}
  };
  const retrieveTestOnly=async()=>{
    setTestBusy(true);
    try {
      const catalog=await listTestBackups(operatorToken);
      if(!catalog.items.length){setStatus('隔离测试库没有保存过草稿');return;}
      const latest=catalog.items.find(item=>item.bundle_id===selectedVaultId)||catalog.items[0];
      const value=await getTestBackup(operatorToken,latest.bundle_id);
      const json=JSON.stringify(value.backup);
      const review=reviewDraftRestore(json,episodes,projects);
      if(!review.ok){setStatus('测试存档无法恢复：'+review.reason);return;}
      Modal.confirm({
        title:'从隔离测试存档恢复到当前浏览器？',
        content:'选择测试存档 '+latest.bundle_id+'。将新增 '+review.draftCount+' 部本地草稿和 '+review.projectCount+' 个本地项目，不会写入正式 Runtime。',
        okText:'确认恢复到浏览器',cancelText:'取消',
        onOk:()=>{onRestore(json);setStatus('已恢复至当前浏览器；正式生产未变化。');}
      });
    }catch(e){setStatus('无法读取隔离存档：'+(e instanceof Error?e.message:'未知错误'));}
    finally{setTestBusy(false);}
  };

  const exportNow=()=>{
    try {
      const text=JSON.stringify(createDraftBackup(episodes,projects),null,2);
      if(text.length>MAX_BACKUP_CHARS){setStatus('草稿内容超过 2MB，暂时无法安全导出；原数据没有被修改');return;}
      const blob=new Blob([text],{type:'application/json;charset=utf-8'});
      const url=URL.createObjectURL(blob);
      const anchor=document.createElement('a');
      anchor.href=url;anchor.download='storyos-local-drafts-'+new Date().toISOString().slice(0,10)+'.json';
      document.body.appendChild(anchor);anchor.click();anchor.remove();
      URL.revokeObjectURL(url);
      setStatus('已触发本机草稿备份下载；请确认文件实际保存成功。没有提交生产 Runtime。');
    }catch {setStatus('导出失败，未更改已有草稿');}
  };
  const receive=async(file:File|null)=>{
    if(!file)return;
    if(file.size>MAX_BACKUP_CHARS*4){setStatus('备份文件太大，已拒绝读取');return;}
    let json:string;
    try{json=await file.text();}catch{setStatus('无法读取文件，未导入任何内容');return;}
    const review=reviewDraftRestore(json,episodes,projects);
    if(!review.ok){setStatus(review.reason);return;}
    Modal.confirm({
      title:'确认恢复浏览器本地草稿？',
      content:'将新增 '+review.draftCount+' 部本地故事草稿、'+review.projectCount+' 个本地项目。此操作只保存到当前浏览器，不创建正式 Runtime Episode、不更改真实图片或生产任务；冲突 ID 一律拒绝覆盖。',
      okText:'确认恢复到本浏览器',cancelText:'取消',
      onOk:()=>{onRestore(json);setStatus('已将通过校验的草稿恢复到当前浏览器，正式 Runtime 未改变。');}
    });
  };
  return <section aria-label="本机草稿备份与迁移准备" className="border-y border-[var(--border-subtle)] py-3 text-[12px]">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 className="os-section-heading">本地草稿保险箱</h2>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">浏览器草稿 {drafts.length} 部 · 本地项目 {projects.length} 个 · 仅备份或恢复当前浏览器数据</p>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="small" onClick={exportNow}>导出草稿备份</Button>
        <Button size="small" onClick={()=>fileRef.current?.click()}>从备份文件恢复</Button>
        <input type="file" ref={fileRef} accept=".json,application/json" aria-label="选择草稿备份JSON文件"
          className="sr-only" onChange={event=>{
            const file=event.currentTarget.files?.[0]||null;
            event.currentTarget.value='';
            void receive(file);
          }}/>
      </div>
    </div>

    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border-subtle)] pt-3">
      <span className="text-[11px] text-[var(--text-tertiary)]">R17 · TEST_ONLY 隔离存档（不等于正式保存）</span>
      <Input.Password size="small" aria-label="隔离测试授权口令" placeholder="隔离测试授权口令（仅保留在内存）" className="!w-[235px]" value={operatorToken} onChange={event=>setOperatorToken(event.target.value)} autoComplete="off"/>
      <Button size="small" disabled={testBusy||operatorToken.trim().length<32} onClick={saveTestOnly}>保存测试存档</Button>
      <Button size="small" disabled={testBusy||operatorToken.trim().length<32} onClick={()=>void reviewVaultList()}>查看隔离存档</Button>
      {vaultItems.length>0&&<Select size="small" aria-label="选择隔离草稿存档" className="!w-[220px]" value={selectedVaultId} onChange={setSelectedVaultId}
        options={vaultItems.map(item=>({value:item.bundle_id,label:item.bundle_id.slice(0,24)}))}/>} 
      <Button size="small" disabled={testBusy||operatorToken.trim().length<32} onClick={()=>void retrieveTestOnly()}>读取选中测试存档</Button>
    </div>
    {status&&<p role="status" className="mt-2 text-[11px] text-[var(--text-secondary)]">{status}</p>}
    <p className="mt-2 text-[11px] text-[var(--text-tertiary)]">
      导入前严格验证格式与 ID 冲突；已存在的草稿/项目一律不覆盖。浏览器数据不是正式项目持久化，跨设备使用请先安全保存备份文件。
    </p>
  </section>;
};
