import test from 'node:test';
import assert from 'node:assert/strict';
import {request} from 'node:http';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {TestMysqlBridge} from '../server/testMysqlBridge.mjs';
import {createDraftMutationServer,listenLocal} from '../server/draftMutationServer.mjs';

process.env.STORYOS_R17_TEST_ONLY='1';
const secret='r17-mysql-browser-qa-operator-1234567890-ABCDEFG';
const origin='http://127.0.0.1:3197',port=19347;
const credentialFile=process.env.STORYOS_R17_MYSQL_TEST_AUTH;
const pythonExe=process.env.STORYOS_R17_PYTHON;
assert.ok(credentialFile && pythonExe,'Explicit TEST_ONLY MySQL file and Python executable required');
const store=new TestMysqlBridge({pythonExe,credentialFile,root:resolve('.')});
const server=createDraftMutationServer(store,{token:secret,port,backend:'mysql8_test_only',allowedBrowserOrigin:origin});
const url='http://127.0.0.1:'+port+'/api/v1/draft-vault';
const raw=(path,method,auth,csrf,body,originValue=origin)=>fetch(url+path,{
 method,
 headers:{ ...(auth?{Authorization:'Bearer '+auth}:{}),
  ...(csrf?{'X-StoryOS-CSRF':csrf}:{}),
  ...(originValue?{Origin:originValue}:{}),
  ...(method==='POST'||method==='PATCH'||method==='DELETE'?{'X-StoryOS-Draft-Intent':'confirmed'}:{}),
  ...(body?{'Content-Type':'application/json'}:{})},
 body:body?JSON.stringify(body):undefined
});
const sample=()=>{
 const id=randomUUID().replaceAll('-','').slice(0,14);
 return {format:'storyos-local-draft-backup',version:1,source:'browser_local_only',
 exportedAt:new Date().toISOString(),
 projects:[{id:'proj-'+id,name:'MySQL QA',createdAt:'2026-10-13',episodeIds:[]}],
 drafts:[{id:'ep-home-'+id,title:'MySQL QA',code:id,synopsis:'Test only',projectId:'proj-'+id,
 frameReviews:[],preflightChecks:[],storyboardBeats:[],characters:[],
 runtimeRequest:{imageModel:'mock-only'},currentStage:'IDEA_LOCK'}]};
};
await listenLocal(server,port);
try{
 await test('R17 Test MySQL: rejects unauthenticated access and legacy bearer',async()=>{
  assert.equal((await raw('','GET')).status,401);
  assert.equal((await raw('','GET',secret)).status,401);
  assert.equal((await raw('/session','POST','wrong')).status,401);
  assert.equal((await raw('/session','POST',secret,null,null,null)).status,403);
  assert.equal((await raw('/session','POST',secret,null,null,'https://evil.example')).status,403);
 });
 const response=await raw('/session','POST',secret);
 assert.equal(response.status,201);
 const session=(await response.json()).data;
 await test('R17 Test MySQL: short-lived scope-bound session, CSRF + Origin',async()=>{
  assert.equal(session.scope,'draft_vault:test_only');
  assert.equal(session.backend,'mysql8_test_only');
  assert.ok(session.expires_at>Date.now()&&session.expires_at<Date.now()+16*60_000);
  assert.equal((await raw('','GET',session.session_token)).status,200);
  assert.equal((await raw('','POST',session.session_token,null,{request_id:'qa-no-csrf',backup:sample()})).status,403);
  assert.equal((await raw('','POST',session.session_token,session.csrf_token,{request_id:'qa-no-origin',backup:sample()},null)).status,403);
  assert.equal((await raw('','GET',session.session_token,null,null,'http://localhost:3100')).status,403);
  const bad=await new Promise((resolve,reject)=>{
   const q=request(url,{headers:{Host:'evil.example',Authorization:'Bearer '+session.session_token}},r=>{r.resume();r.once('end',()=>resolve(r.statusCode));});
   q.once('error',reject);q.end();
  });
  assert.equal(bad,403);
  assert.equal((await raw('/anything','GET',session.session_token)).status,404);
 });
 await test('R17 Test MySQL: actual HTTP → MySQL persistent → cross-session retrieve',async()=>{
  const backup=sample(),rid='req-'+randomUUID();
  const a=await raw('','POST',session.session_token,session.csrf_token,{request_id:rid,backup});
  assert.equal(a.status,201);
  const created=(await a.json()).data;
  assert.equal(created.production_created,false);
  assert.equal(created.test_only,true);
  assert.match(created.bundle_id,/^TEST_BUNDLE_/);
  const retry=await raw('','POST',session.session_token,session.csrf_token,{request_id:rid,backup});
  assert.equal(retry.status,201);
  assert.deepEqual((await retry.json()).data,created);
  const conflict=await raw('','POST',session.session_token,session.csrf_token,{request_id:rid,backup:{...backup,drafts:[]}});
  assert.equal(conflict.status,409);
  assert.equal((await conflict.json()).code,'IDEMPOTENCY_CONFLICT');
  const secondSession=await raw('/session','POST',secret);
  assert.equal(secondSession.status,201);
  const second=(await secondSession.json()).data;
  const listing=await raw('','GET',second.session_token);
  assert.equal(listing.status,200);
  const entries=(await listing.json()).data.items;
  assert.ok(entries.some(item=>item.bundle_id===created.bundle_id));
  const restored=await raw('/'+created.bundle_id,'GET',second.session_token);
  assert.equal(restored.status,200);
  assert.equal((await restored.json()).data.backup.drafts[0].id,backup.drafts[0].id);
  assert.equal((await raw('/session','DELETE',second.session_token,second.csrf_token)).status,200);
  assert.equal((await raw('','GET',second.session_token)).status,401);
 });
 await test('R17 Test MySQL: revoke old operator session and reject re-use',async()=>{
  assert.equal((await raw('/session','DELETE',session.session_token,session.csrf_token)).status,200);
  assert.equal((await raw('','GET',session.session_token)).status,401);
  assert.equal((await raw('','GET',secret)).status,401);
 });

}finally{
 await new Promise(resolve=>server.close(resolve));
}