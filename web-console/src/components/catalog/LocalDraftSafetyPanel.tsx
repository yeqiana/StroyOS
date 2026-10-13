import React, {useRef, useState} from 'react';
import {Button, Modal, Input, Select} from 'antd';
import {saveTestBackup,listTestBackups,getTestBackup,saveWorkspace,listWorkspaces,getWorkspace} from '../../api/isolatedDraftVault';
import type {SavedWorkspaceItem} from '../../api/isolatedDraftVault';
import {saveWebDraft,listWebDrafts,readWebDraft} from '../../api/webDraftApi';
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
  const [savedWorkspace,setSavedWorkspace]=useState<{workspace_id:string;version:number}|undefined>(()=>{
    try {const raw=localStorage.getItem('storyos_r17_last_test_workspace');if(raw){const value=JSON.parse(raw);
      if(typeof value.workspace_id==='string'&&/^TEST_WORKSPACE_[a-f0-9-]{36}$/.test(value.workspace_id)
        &&Number.isSafeInteger(value.version)&&value.version>0)return value;}}catch{}return undefined;
  });
  const [workspaceItems,setWorkspaceItems]=useState<SavedWorkspaceItem[]>([]);
  const [selectedWorkspaceId,setSelectedWorkspaceId]=useState<string|undefined>();

  const [webSecret,setWebSecret]=useState('');
  const [webBusy,setWebBusy]=useState(false);
  const [webItems,setWebItems]=useState<Array<{workspace_id:string;version:number;updated_at:string}>>([]);
  const [webSelected,setWebSelected]=useState<string|undefined>();
  const [webCurrent,setWebCurrent]=useState<{workspace_id:string;version:number}|undefined>(()=>{
    try{
      const value=JSON.parse(localStorage.getItem('storyos_web_draft_workspace')||'null');
      if(value&&/^WDW_[a-f0-9-]{36}$/.test(value.workspace_id)
        &&Number.isSafeInteger(value.version)&&value.version>0)return value;
    }catch{}
    return undefined;
  });
  const saveOfficialDraft=()=>{
    Modal.confirm({
      title:'保存服务端草稿？',
      content:'将当前浏览器的自建项目和故事草稿存入独立草稿数据库；不创建正式生产 Episode，不启动图片生成。',
      okText:'保存草稿',cancelText:'取消',
      onOk:async()=>{
        setWebBusy(true);
        try{
          const result=await saveWebDraft(webSecret,createDraftBackup(episodes,projects),webCurrent);
          const next={workspace_id:result.workspace_id,version:result.version};
          localStorage.setItem('storyos_web_draft_workspace',JSON.stringify(next));
          setWebCurrent(next);
          setStatus('服务端草稿已保存（v'+result.version+'），未创建正式生产 Episode');
        }catch(e){setStatus('服务端草稿未保存：'+(e instanceof Error?e.message:'未知错误'));}
        finally{setWebBusy(false);}
      }
    });
  };
  const viewOfficialDrafts=async()=>{
    setWebBusy(true);
    try{
      const result=await listWebDrafts(webSecret);
      setWebItems(result.items);
      setWebSelected(result.items[0]?.workspace_id);
      setStatus('服务端共有 '+result.items.length+' 份草稿工作区；未启动生产');
    }catch(e){setStatus('草稿列表不可用：'+(e instanceof Error?e.message:'未知错误'));}
    finally{setWebBusy(false);}
  };
  const restoreOfficialDraft=async()=>{
    if(!webSelected)return;
    setWebBusy(true);
    try{
      const record=await readWebDraft(webSecret,webSelected);
      const raw=JSON.stringify(record.backup);
      const check=reviewDraftRestore(raw,episodes,projects);
      if(!check.ok){setStatus(check.reason);return;}
      Modal.confirm({
        title:'将服务端草稿恢复到此浏览器？',
        content:'新增 '+check.projectCount+' 个项目、'+check.draftCount+' 部草稿；已存在的 ID 一律拒绝覆盖。',
        okText:'确认恢复',cancelText:'取消',
        onOk:()=>{
          onRestore(raw);
          const next={workspace_id:record.workspace_id,version:record.version};
          setWebCurrent(next);
          localStorage.setItem('storyos_web_draft_workspace',JSON.stringify(next));
          setStatus('已从服务端恢复草稿（v'+record.version+'），未触发生产');
        }
      });
    }catch(e){setStatus('服务端草稿恢复失败：'+(e instanceof Error?e.message:'未知错误'));}
    finally{setWebBusy(false);}
  };

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


  // Server stores a versioned snapshot of browser drafts, not a Runtime Episode.
  const saveWorkspaceNow=()=>{
    Modal.confirm({
      title:'保存到隔离 MySQL 草稿工作区？',
      content:'保存现有自建项目和草稿的快照，不创建正式 Episode，也不会触发生产。',
      okText:'确认保存草稿',cancelText:'取消',
      onOk:async()=>{
        setTestBusy(true);
        try{
          const result=await saveWorkspace(operatorToken,createDraftBackup(episodes,projects),savedWorkspace);
          const current={workspace_id:result.workspace_id,version:result.version};
          setSavedWorkspace(current);
          localStorage.setItem('storyos_r17_last_test_workspace',JSON.stringify(current));
          setStatus('已保存隔离 MySQL 草稿 · 版本 '+result.version+'；正式 Runtime 未变化');
        }catch(error){
          setStatus('保存失败（可能版本冲突）：'+(error instanceof Error?error.message:'未知错误'));
        }finally{setTestBusy(false);}
      }
    });
  };
  const refreshWorkspaces=async()=>{
    setTestBusy(true);
    try{
      const result=await listWorkspaces(operatorToken);
      setWorkspaceItems(result.items);
      setSelectedWorkspaceId(result.items[0]?.workspace_id);
      setStatus('已从隔离 MySQL 读取 '+result.items.length+' 份草稿工作区');
    }catch(error){
      setStatus('查询工作区失败：'+(error instanceof Error?error.message:'未知错误'));
    }finally{setTestBusy(false);}
  };
  const restoreWorkspace=async()=>{
    if(!selectedWorkspaceId)return;
    setTestBusy(true);
    try{
      const result=await getWorkspace(operatorToken,selectedWorkspaceId);
      const json=JSON.stringify(result.backup);
      const reviewed=reviewDraftRestore(json,episodes,projects);
      if(!reviewed.ok){setStatus(reviewed.reason);return;}
      Modal.confirm({
        title:'恢复隔离 MySQL 工作区到本浏览器？',
        content:'新增 '+reviewed.projectCount+' 个本地项目、'+reviewed.draftCount+' 部本地草稿。冲突 ID 一律不覆盖。',
        okText:'确认恢复',cancelText:'取消',
        onOk:()=>{
          onRestore(json);
          const current={workspace_id:selectedWorkspaceId,version:result.version};
          setSavedWorkspace(current);
          localStorage.setItem('storyos_r17_last_test_workspace',JSON.stringify(current));
          setStatus('草稿已恢复到浏览器；未创建正式 Runtime 作品');
        }
      });
    }catch(error){
      setStatus('读取工作区失败：'+(error instanceof Error?error.message:'未知错误'));
    }finally{setTestBusy(false);}
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

    <div className="mt-2 flex flex-wrap items-center gap-2">
      <span className="text-[11px] text-[var(--text-tertiary)]">隔离 MySQL 草稿工作区 · 保存后可继续编辑</span>
      <Button size="small" disabled={testBusy||operatorToken.trim().length<32}
        onClick={saveWorkspaceNow}>保存当前项目和草稿</Button>
      <Button size="small" disabled={testBusy||operatorToken.trim().length<32}
        onClick={()=>void refreshWorkspaces()}>刷新服务端草稿列表</Button>
      {workspaceItems.length>0&&<Select size="small" aria-label="选择服务端草稿工作区"
        className="!w-[215px]" value={selectedWorkspaceId} onChange={setSelectedWorkspaceId}
        options={workspaceItems.map(item=>({value:item.workspace_id,label:item.workspace_id.slice(0,23)+' · v'+item.version}))}/>}
      <Button size="small" disabled={testBusy||!selectedWorkspaceId||operatorToken.trim().length<32}
        onClick={()=>void restoreWorkspace()}>恢复选中工作区</Button>
      {savedWorkspace&&<span className="text-[11px] text-[var(--text-tertiary)]">本机正在编辑 v{savedWorkspace.version}</span>}
    </div>

    <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border-subtle)] pt-3">
      <span className="text-[11px] text-[var(--text-tertiary)]">服务端草稿 · 正式保存，不启动生产</span>
      <Input.Password size="small" aria-label="服务端草稿操作口令" placeholder="草稿操作口令"
        className="!w-[200px]" autoComplete="off" value={webSecret}
        onChange={event=>setWebSecret(event.target.value)}/>
      <Button size="small" disabled={webBusy||webSecret.trim().length<32}
        onClick={saveOfficialDraft}>保存到服务端</Button>
      <Button size="small" disabled={webBusy||webSecret.trim().length<32}
        onClick={()=>void viewOfficialDrafts()}>查看服务端草稿</Button>
      {webItems.length>0&&<Select size="small" aria-label="选择正式服务端草稿"
        value={webSelected} className="!w-[210px]" onChange={setWebSelected}
        options={webItems.map(item=>({value:item.workspace_id,
          label:item.workspace_id.slice(0,18)+' · v'+item.version}))}/>}
      <Button size="small" disabled={webBusy||!webSelected||webSecret.trim().length<32}
        onClick={()=>void restoreOfficialDraft()}>恢复选中草稿</Button>
      {webCurrent&&<span className="text-[11px] text-[var(--text-tertiary)]">当前 v{webCurrent.version}</span>}
    </div>
    {status&&<p role="status" className="mt-2 text-[11px] text-[var(--text-secondary)]">{status}</p>}
    <p className="mt-2 text-[11px] text-[var(--text-tertiary)]">
      导入前严格验证格式与 ID 冲突；已存在的草稿/项目一律不覆盖。浏览器数据不是正式项目持久化，跨设备使用请先安全保存备份文件。
    </p>
  </section>;
};
