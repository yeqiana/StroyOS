import {DatabaseSync} from 'node:sqlite';
import {createHash,randomUUID} from 'node:crypto';
import {mkdirSync} from 'node:fs';
import {basename,dirname,resolve} from 'node:path';
const BASE='/api/v1/draft-vault';
const stamp=()=>new Date().toISOString();
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
export class VaultError extends Error{
 constructor(status,code,message){super(message);this.status=status;this.code=code;}
}
const reject=(status,code,message)=>{throw new VaultError(status,code,message);};
function checkBackup(b){
 if(!b||b.format!=='storyos-local-draft-backup'||b.version!==1||b.source!=='browser_local_only'||!Array.isArray(b.drafts)||!Array.isArray(b.projects)||b.drafts.length>100||b.projects.length>100)reject(422,'INVALID_BACKUP','必须提交 R16 浏览器草稿备份');
 const projects=new Set(), drafts=new Set();
 for(const p of b.projects){
  if(!p||!/^proj-[a-zA-Z0-9_-]{1,70}$/.test(p.id)||typeof p.name!=='string'||!p.name.trim()||p.name.length>220||projects.has(p.id))reject(422,'INVALID_PROJECT','项目结构或 ID 冲突');
  projects.add(p.id);
 }
 for(const d of b.drafts){
  if(!d||!/^ep-(home|proj)-[a-zA-Z0-9_-]{1,70}$/.test(d.id)||typeof d.title!=='string'||!d.title.trim()||d.title.length>220||typeof d.synopsis!=='string'||!Array.isArray(d.frameReviews)||!Array.isArray(d.preflightChecks)||!d.runtimeRequest||drafts.has(d.id))reject(422,'INVALID_DRAFT','草稿结构或 ID 冲突');
  if(d.projectId&&!projects.has(d.projectId)&&!['proj-aigc-dali','proj-storyos','proj-urban','proj-relic'].includes(d.projectId))reject(422,'PROJECT_MISSING','草稿引用不存在的项目');
  drafts.add(d.id);
 }
}
export class IsolatedDraftStore{
 constructor(dbPath,{testOnly=false}={}){
  if(!testOnly||process.env.STORYOS_R17_TEST_ONLY!=='1')reject(403,'TEST_ONLY_REQUIRED','必须显式启用隔离测试模式');
  const file=resolve(dbPath);
  if(!file.toLowerCase().split(/[\\/]/).includes('r17-test-only')||basename(file)!=='draft-vault.sqlite')reject(403,'UNSAFE_DB_PATH','仅允许 r17-test-only/draft-vault.sqlite');
  mkdirSync(dirname(file),{recursive:true});
  this.db=new DatabaseSync(file);
  this.db.exec('PRAGMA journal_mode=WAL;PRAGMA foreign_keys=ON;PRAGMA busy_timeout=3000;');
  this.db.exec([
   'CREATE TABLE IF NOT EXISTS bundles(id TEXT PRIMARY KEY,version INTEGER NOT NULL,sha TEXT NOT NULL UNIQUE,content TEXT NOT NULL,created_at TEXT NOT NULL);',
   'CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL REFERENCES bundles(id),source_id TEXT NOT NULL UNIQUE,title TEXT NOT NULL);',
   'CREATE TABLE IF NOT EXISTS drafts(id TEXT PRIMARY KEY,bundle_id TEXT NOT NULL REFERENCES bundles(id),source_id TEXT NOT NULL UNIQUE,title TEXT NOT NULL,version INTEGER NOT NULL);',
   'CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,sha TEXT NOT NULL,result TEXT NOT NULL);',
   'CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,action TEXT NOT NULL,subject TEXT NOT NULL,request_id TEXT NOT NULL,time TEXT NOT NULL);'
  ].join(''));
 }
 close(){this.db.close();}
 transaction(fn){this.db.exec('BEGIN IMMEDIATE');try{const r=fn();this.db.exec('COMMIT');return r;}catch(e){this.db.exec('ROLLBACK');throw e;}}
 once(id,payload,fn){
  if(typeof id!=='string'||!/^[a-zA-Z0-9_-]{1,100}$/.test(id))reject(400,'INVALID_REQUEST_ID','缺少合法 request_id');
  return this.transaction(()=>{
   const sha=hash(payload),prev=this.db.prepare('SELECT sha,result FROM requests WHERE id=?').get(id);
   if(prev){if(prev.sha!==sha)reject(409,'IDEMPOTENCY_CONFLICT','同一请求 ID 的内容不同');return JSON.parse(prev.result);}
   const result=fn();this.db.prepare('INSERT INTO requests VALUES(?,?,?)').run(id,sha,JSON.stringify(result));return result;
  });
 }
 importBackup({request_id,backup}={}){
  if(!backup||JSON.stringify(backup).length>2000000)reject(413,'BACKUP_TOO_LARGE','文件超出隔离服务限制');
  checkBackup(backup);
  return this.once(request_id,{operation:'import',backup},()=>{
   if(this.db.prepare('SELECT 1 FROM bundles WHERE sha=?').get(hash(backup)))reject(409,'BACKUP_DUPLICATE','相同备份已存档');
   for(const p of backup.projects)if(this.db.prepare('SELECT 1 FROM projects WHERE source_id=?').get(p.id))reject(409,'PROJECT_CONFLICT','项目来源 ID 已存在');
   for(const d of backup.drafts)if(this.db.prepare('SELECT 1 FROM drafts WHERE source_id=?').get(d.id))reject(409,'DRAFT_CONFLICT','草稿来源 ID 已存在');
   const id='TEST_BUNDLE_'+randomUUID();
   this.db.prepare('INSERT INTO bundles VALUES(?,?,?,?,?)').run(id,1,hash(backup),JSON.stringify(backup),stamp());
   for(const p of backup.projects)this.db.prepare('INSERT INTO projects VALUES(?,?,?,?)').run('TEST_PROJECT_'+randomUUID(),id,p.id,p.name);
   for(const d of backup.drafts)this.db.prepare('INSERT INTO drafts VALUES(?,?,?,?,?)').run('TEST_DRAFT_'+randomUUID(),id,d.id,d.title,1);
   this.db.prepare('INSERT INTO audit VALUES(?,?,?,?,?)').run(randomUUID(),'IMPORT_TEST_ONLY',id,request_id,stamp());
   return {bundle_id:id,version:1,projects:backup.projects.length,drafts:backup.drafts.length,production_created:false};
  });
 }
 list(){return {items:this.db.prepare('SELECT id AS bundle_id,version,created_at FROM bundles ORDER BY created_at DESC LIMIT 100').all(),test_only:true,production_created:false};}
 get(id){
  const r=this.db.prepare('SELECT id,version,content FROM bundles WHERE id=?').get(id);
  if(!r)reject(404,'NOT_FOUND','草稿存档不存在');
  return {bundle_id:r.id,version:r.version,backup:JSON.parse(r.content),test_only:true};
 }
 rename(id,{request_id,expected_version,title}={}){
  if(!Number.isSafeInteger(expected_version)||expected_version<1||typeof title!=='string'||!title.trim()||title.length>220)reject(422,'INVALID_VERSION','需要合法版本和标题');
  return this.once(request_id,{operation:'rename',id,expected_version,title},()=>{
   const r=this.db.prepare('UPDATE drafts SET title=?,version=version+1 WHERE id=? AND version=?').run(title,id,expected_version);
   if(r.changes!==1)reject(409,'VERSION_CONFLICT','草稿版本已更新或不存在');
   this.db.prepare('INSERT INTO audit VALUES(?,?,?,?,?)').run(randomUUID(),'RENAME_TEST_ONLY',id,request_id,stamp());
   return {draft_id:id,version:expected_version+1,title};
  });
 }
 execute(method,path,body){
  if(method==='GET'&&path===BASE)return [200,this.list()];
  if(method==='POST'&&path===BASE)return [201,this.importBackup(body)];
  if(method==='GET'&&/^\/api\/v1\/draft-vault\/TEST_BUNDLE_[a-f0-9-]{36}$/.test(path))return [200,this.get(path.slice(BASE.length+1))];
  if(method==='PATCH'&&/^\/api\/v1\/draft-vault\/drafts\/TEST_DRAFT_[a-f0-9-]{36}$/.test(path))return [200,this.rename(path.slice((BASE+'/drafts/').length),body)];
  reject(404,'ROUTE_NOT_FOUND','接口不存在');
 }
}