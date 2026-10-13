import {spawn} from 'node:child_process';
import {isAbsolute,resolve,basename,dirname} from 'node:path';
import {existsSync} from 'node:fs';

export class WebDraftBridge {
 constructor({pythonExe,authFile,root=process.cwd(),testOnly=false}={}){
  if(!pythonExe||!existsSync(pythonExe)||!authFile||!isAbsolute(authFile)
    ||basename(authFile)!=='web-draft-auth.json'
    ||basename(dirname(authFile))!=='web-drafts'
    ||basename(dirname(dirname(authFile)))!=='.storyos-tmp'
    ||!existsSync(authFile)
    ||!existsSync(resolve(root,'scripts/storyos_web_draft_cli.py')))
    throw Error('Explicit scoped Web draft configuration is required');
  this.pythonExe=pythonExe;this.authFile=authFile;this.root=resolve(root);this.testOnly=testOnly;this.inflight=0;
 }
 execute(method,path,body={}){
  if(this.inflight>=6)return Promise.reject(Object.assign(Error('草稿库繁忙'),{status:429,code:'DRAFT_BUSY'}));
  if(!['GET','POST','PUT'].includes(method)||!/^\/api\/v1\/web-drafts(?:\/WDW_[a-f0-9-]{36}(?:\/handoff-plan)?)?$/.test(path))
    return Promise.reject(Object.assign(Error('路由无效'),{status:404,code:'ROUTE_NOT_FOUND'}));
  const json=JSON.stringify({method,path,body});
  if(Buffer.byteLength(json)>2_100_000)
    return Promise.reject(Object.assign(Error('内容过大'),{status:413,code:'BODY_TOO_LARGE'}));
  this.inflight++;
  return new Promise((resolveResult,reject)=>{
   const env={...process.env,STORYOS_WEB_DRAFTS_AUTH:this.authFile,
     STORYOS_WEB_DRAFTS_TEST_ONLY:this.testOnly?'1':'0',
     STORYOS_WEB_DRAFTS_ENABLE:this.testOnly?'0':'1'};
   const processChild=spawn(this.pythonExe,['-m','scripts.storyos_web_draft_cli'],
     {cwd:this.root,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
   let output='',done=false;
   const end=(err,value)=>{if(done)return;done=true;clearTimeout(timer);this.inflight--;err?reject(err):resolveResult(value);};
   const timer=setTimeout(()=>{processChild.kill();end(Object.assign(Error('草稿库超时'),{status:503,code:'DRAFT_TIMEOUT'}));},13000);
   processChild.stdout.setEncoding('utf8');
   processChild.stdout.on('data',d=>{output+=d;if(output.length>2_300_000)processChild.kill();});
   processChild.stderr.resume();
   processChild.on('error',()=>end(Object.assign(Error('草稿库接口未启动'),{status:503,code:'BRIDGE_UNAVAILABLE'})));
   processChild.on('close',code=>{
    if(done)return;
    if(code!==0||output.length>2_300_000)return end(Object.assign(Error('草稿库调用失败'),{status:503,code:'BRIDGE_FAILED'}));
    try{
     const row=JSON.parse(output);
     if(!Number.isInteger(row.status)||row.status<200||row.status>=600)throw Error('bad receipt');
     if(row.status>=400)return end(Object.assign(Error(row.message||row.code),{status:row.status,code:row.code}));
     end(null,[row.status,row.data]);
    }catch(err){end(Object.assign(Error('草稿库回执不完整'),{status:503,code:'RECEIPT_INVALID'}));}
   });
   processChild.stdin.on('error',()=>{});
   processChild.stdin.end(json);
  });
 }
}