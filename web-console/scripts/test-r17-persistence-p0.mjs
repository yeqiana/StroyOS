import test from 'node:test';
import {request} from 'node:http';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {IsolatedDraftStore} from '../server/draftStore.mjs';
import {createDraftMutationServer,listenLocal} from '../server/draftMutationServer.mjs';
process.env.STORYOS_R17_TEST_ONLY='1';
const token='r17-test-operator-12345678901234567890';
const backup=()=>({format:'storyos-local-draft-backup',version:1,source:'browser_local_only',
 projects:[{id:'proj-test-001',name:'test',episodeIds:[],createdAt:'2026-10-13'}],
 drafts:[{id:'ep-home-test-001',title:'original',code:'test',synopsis:'story',projectId:'proj-test-001',
 frameReviews:[],preflightChecks:[],runtimeRequest:{mode:'auto_create'},storyboardBeats:[],characters:[],currentStage:'IDEA_LOCK'}]});
const fresh=()=>{const base=mkdtempSync(join(tmpdir(),'r17-qa-'));
 const file=join(base,'r17-test-only','draft-vault.sqlite');return {base,file,store:new IsolatedDraftStore(file,{testOnly:true})};};
test('R17 idempotency, conflict, rollback and persistence',()=>{
 const {base,file,store}=fresh();
 try{
  const b=backup(),r=store.importBackup({request_id:'req-1',backup:b});
  assert.equal(r.production_created,false);
  assert.deepEqual(store.importBackup({request_id:'req-1',backup:b}),r);
  assert.throws(()=>store.importBackup({request_id:'req-1',backup:{...b,drafts:[]}}),e=>e.code==='IDEMPOTENCY_CONFLICT');
  assert.throws(()=>store.importBackup({request_id:'req-2',backup:b}),e=>e.code==='BACKUP_DUPLICATE');
  assert.throws(()=>store.importBackup({request_id:'req-3',backup:{...b,drafts:[{...b.drafts[0],title:'other'}]}}),e=>e.code==='PROJECT_CONFLICT');
  assert.equal(store.list().items.length,1);
  assert.equal(store.get(r.bundle_id).backup.drafts[0].title,'original');
  const id=store.db.prepare('SELECT id FROM drafts').get().id;
  const updated=store.rename(id,{request_id:'req-4',expected_version:1,title:'updated'});
  assert.equal(updated.version,2);
  assert.deepEqual(store.rename(id,{request_id:'req-4',expected_version:1,title:'updated'}),updated);
  assert.throws(()=>store.rename(id,{request_id:'req-5',expected_version:1,title:'stale'}),e=>e.code==='VERSION_CONFLICT');
  assert.equal(store.db.prepare('SELECT count(*) as n FROM audit').get().n,2);
  store.close();
  const reopened=new IsolatedDraftStore(file,{testOnly:true});
  assert.equal(reopened.list().items.length,1);reopened.close();
 }finally{try{store.close();}catch{}rmSync(base,{recursive:true,force:true});}
});
test('R17 authentication, CSRF, Host validation and no CORS',async()=>{
 const {base,store}=fresh();const port=19333;
 const server=createDraftMutationServer(store,{port,token});
 await listenLocal(server,port);
 const url='http://127.0.0.1:'+port+'/api/v1/draft-vault';
 const send=(method,secret,origin='http://127.0.0.1:3100',intent='confirmed',value)=>fetch(url,{
  method,headers:{...(secret?{Authorization:'Bearer '+secret}:{}),...(origin?{Origin:origin}:{}),
   ...(intent?{'X-StoryOS-Draft-Intent':intent}:{}),'Content-Type':'application/json'},
  body:value?JSON.stringify(value):undefined});
 try{
  assert.equal((await send('GET',null)).status,401);
  assert.equal((await send('GET','incorrect')).status,401);
  assert.equal((await send('GET',token,'https://attacker.example')).status,403);
  assert.equal((await send('POST',token,null,'confirmed',{request_id:'req-1',backup:backup()})).status,403);
  assert.equal((await send('POST',token,'http://127.0.0.1:3100',null,{request_id:'req-1',backup:backup()})).status,403);
  assert.equal((await send('DELETE',token)).status,405);
  const ok=await send('POST',token,'http://127.0.0.1:3100','confirmed',{request_id:'req-1',backup:backup()});
  assert.equal(ok.status,201);assert.equal((await ok.json()).data.production_created,false);
  const list=await send('GET',token);
  assert.equal(list.status,200);
  assert.equal((await list.json()).data.items.length,1);
  assert.equal(list.headers.get('access-control-allow-origin'),null);
  const spoofed=await new Promise((resolve,reject)=>{const r=request(url,{headers:{Host:'evil.example',Authorization:'Bearer '+token}},s=>{s.resume();s.on('end',()=>resolve(s.statusCode));});r.once('error',reject);r.end();});
  assert.equal(spoofed,403);
 }finally{await new Promise(done=>server.close(done));store.close();rmSync(base,{recursive:true,force:true});}
});
test('R17 must fail closed unless TEST_ONLY and safe path',()=>{
 assert.throws(()=>new IsolatedDraftStore('D:/production/data.sqlite',{testOnly:true}),e=>e.code==='UNSAFE_DB_PATH');
 assert.throws(()=>new IsolatedDraftStore('r17-test-only/draft-vault.sqlite',{testOnly:false}),e=>e.code==='TEST_ONLY_REQUIRED');
});
