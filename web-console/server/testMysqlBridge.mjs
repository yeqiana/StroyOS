import {spawn} from 'node:child_process';
import {isAbsolute, resolve, basename, dirname} from 'node:path';
import {existsSync} from 'node:fs';
const ROUTES='/api/v1/draft-vault';
export class TestMysqlBridge {
 constructor({pythonExe,credentialFile,root=process.cwd()}={}){
  if(process.env.STORYOS_R17_TEST_ONLY!=='1')throw Error('TEST_ONLY is required');
  if(!pythonExe||!existsSync(pythonExe))throw Error('Explicit Python executable required');
  if(!credentialFile||!isAbsolute(credentialFile)||basename(credentialFile)!=='mysql-auth.json'
    ||basename(dirname(credentialFile))!=='r17-test-only')throw Error('Explicit test-only auth file required');
  if(!existsSync(credentialFile))throw Error('Test-only MySQL credentials missing');
  this.pythonExe=pythonExe;this.credentialFile=credentialFile;this.root=resolve(root);
  this.inflight=0;
 }
 execute(method,path,body={}){
  if(this.inflight>=6)return Promise.reject(Object.assign(Error('隔离测试库繁忙'),{status:429,code:'TEST_BUSY'}));
  if(!['GET','POST','PATCH'].includes(method)||!path.startsWith(ROUTES)||path.includes('?'))
   return Promise.reject(Object.assign(Error('路由不可用'),{status:404,code:'ROUTE_NOT_FOUND'}));
  const json=JSON.stringify({method,path,body});
  if(Buffer.byteLength(json)>2_100_000)
   return Promise.reject(Object.assign(Error('备份超过限制'),{status:413,code:'REQUEST_TOO_LARGE'}));
  this.inflight++;
  return new Promise((ok,no)=>{
   const args=['-m','scripts.storyos_r17_vault_cli'];
   const child=spawn(this.pythonExe,args,{
     cwd:this.root,windowsHide:true,stdio:['pipe','pipe','pipe'],
     env:{...process.env,STORYOS_R17_TEST_ONLY:'1',STORYOS_R17_MYSQL_TEST_AUTH:this.credentialFile}
   });
   let output='',stderr='',done=false;
   const complete=(err,result)=>{if(done)return;done=true;clearTimeout(timer);this.inflight--;err?no(err):ok(result);};
   const timer=setTimeout(()=>{child.kill();complete(Object.assign(Error('隔离测试库请求超时'),{status:503,code:'TEST_MYSQL_TIMEOUT'}));},12_000);
   child.stdout.setEncoding('utf8');
   child.stdout.on('data',s=>{output+=s;if(output.length>2_200_000)child.kill();});
   child.stderr.setEncoding('utf8');
   child.stderr.on('data',s=>{stderr+=s.slice(0,256);});
   child.on('error',()=>complete(Object.assign(Error('隔离测试桥不可用'),{status:503,code:'BRIDGE_UNAVAILABLE'})));
   child.on('close',code=>{
    if(done)return;
    if(code!==0||output.length>2_200_000)return complete(Object.assign(Error('隔离数据库调用失败'),{status:503,code:'BRIDGE_FAILED'}));
    try{
     const response=JSON.parse(output);
     if(!Number.isInteger(response.status)||response.status<200||response.status>=600)throw Error('bad response');
     if(response.status>=400)return complete(Object.assign(Error(response.message||response.code),{status:response.status,code:response.code||'TEST_MYSQL_ERROR'}));
     complete(null,[response.status,response.data]);
    }catch(e){complete(Object.assign(Error('隔离数据库回执错误'),{status:503,code:'BRIDGE_RECEIPT_INVALID'}));}
   });
   child.stdin.on('error',()=>{});
   child.stdin.end(json);
  });
 }
}