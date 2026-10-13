import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {request} from 'node:http';
import {resolve} from 'node:path';
import {WebDraftBridge} from '../server/webDraftBridge.mjs';
import {createWebDraftServer,listenLocal} from '../server/webDraftServer.mjs';

process.env.STORYOS_WEB_DRAFTS_TEST_ONLY='1';
const token='web-draft-test-session-token-a1b2c3d4e5f67890';
const port=19419,origin='http://127.0.0.1:3199';
const bridge=new WebDraftBridge({pythonExe:process.env.STORYOS_WEB_DRAFTS_PYTHON,
 authFile:process.env.STORYOS_WEB_DRAFTS_AUTH,root:resolve('.'),testOnly:true});
const server=createWebDraftServer(bridge,{token,port,allowedBrowserOrigin:origin,
 backend:'mysql8_draft_canary'});
const url='http://127.0.0.1:'+port+'/api/v1/web-drafts';
const fetchIt=(path,method,secret,csrf,body,originValue=origin)=>{
 const write=method!=='GET';
 return fetch(url+path,{method,headers:{...(secret?{Authorization:'Bearer '+secret}:{}),
  ...(originValue?{Origin:originValue}:{}),
  ...(write?{'X-StoryOS-Draft-Intent':'confirmed'}:{}),
  ...(csrf?{'X-StoryOS-CSRF':csrf}:{}),
  ...(body?{'Content-Type':'application/json'}:{})},
 body:body?JSON.stringify(body):undefined});
};
const backup=()=>{
 const uid=randomUUID().replaceAll('-','').slice(0,12);
 return {format:'storyos-local-draft-backup',version:1,source:'browser_local_only',
 exportedAt:'2026-10-13T01:23:00Z',projects:[{id:'proj-'+uid,name:'Browser project',
 createdAt:'2026-10-13',episodeIds:[]}],drafts:[{id:'ep-home-'+uid,
 projectId:'proj-'+uid,title:'From Chrome',code:uid,synopsis:'text only',
 frameReviews:[],preflightChecks:[],storyboardBeats:[],characters:[],
 currentStage:'IDEA_LOCK',runtimeRequest:{mode:'draft_only'}}]};
};
await listenLocal(server,port);
try{
 await test('untrusted clients are rejected',async()=>{
  assert.equal((await fetchIt('','GET')).status,401);
  assert.equal((await fetchIt('','GET',token)).status,401);
  assert.equal((await fetchIt('/session','POST','invalid')).status,401);
  assert.equal((await fetchIt('/session','POST',token,undefined,undefined,'https://attacker.example')).status,403);
  assert.equal((await fetchIt('/session','POST',token,undefined,undefined,null)).status,403);
 });
 const login=await fetchIt('/session','POST',token);
 assert.equal(login.status,201);
 const session=(await login.json()).data;
 await test('scoped short-lived authenticated CSRF session',async()=>{
  assert.equal(session.scope,'web_drafts:draft_only');
  assert.equal(session.draft_only,true);
  assert.equal(session.canonical_episode_created,false);
  assert.equal((await fetchIt('','GET',session.session_token)).status,200);
  assert.equal((await fetchIt('','POST',session.session_token,undefined,
   {request_id:randomUUID(),backup:backup()})).status,403);
  const host=await new Promise((ok,no)=>{
   const r=request(url,{headers:{Host:'attacker.invalid',Authorization:'Bearer '+session.session_token}},
   s=>{s.resume();s.on('end',()=>ok(s.statusCode));});r.on('error',no);r.end();
  });
  assert.equal(host,403);
 });
 await test('server draft identities survive update, conflict and independent session',async()=>{
  const draft=backup(),id='req_'+randomUUID();
  const save=await fetchIt('','POST',session.session_token,session.csrf_token,{request_id:id,backup:draft});
  assert.equal(save.status,201);
  const created=(await save.json()).data;
  assert.equal(created.canonical_episode_created,false);
  assert.equal(created.production_started,false);
  assert.match(created.workspace_id,/^WDW_[0-9a-f-]{36}$/);
  assert.equal(Object.keys(created.identity_map.drafts).length,1);
  const retry=await fetchIt('','POST',session.session_token,session.csrf_token,{request_id:id,backup:draft});
  assert.deepEqual((await retry.json()).data,created);
  const edited={...draft,drafts:[{...draft.drafts[0],title:'Updated'}]};
  const url='/'+created.workspace_id;
  const updated=await fetchIt(url,'PUT',session.session_token,session.csrf_token,
   {request_id:'req_'+randomUUID(),backup:edited,expected_version:1});
  assert.equal(updated.status,200);
  const second=(await updated.json()).data;
  assert.equal(second.version,2);
  assert.deepEqual(second.identity_map,created.identity_map);
  const stale=await fetchIt(url,'PUT',session.session_token,session.csrf_token,
   {request_id:'req_'+randomUUID(),backup:draft,expected_version:1});
  assert.equal(stale.status,409);
  assert.equal((await stale.json()).code,'VERSION_CONFLICT');
  const session2=(await (await fetchIt('/session','POST',token)).json()).data;
  const read=await fetchIt(url,'GET',session2.session_token);
  assert.equal(read.status,200);
  const restored=(await read.json()).data;
  assert.equal(restored.version,2);
  assert.equal(restored.backup.drafts[0].title,'Updated');
  assert.equal(restored.identity_map.drafts[draft.drafts[0].id],created.identity_map.drafts[draft.drafts[0].id]);
  const preview=await fetchIt(url+'/handoff-plan','GET',session2.session_token);
  assert.equal(preview.status,200);
  const plan=(await preview.json()).data;
  assert.equal(plan.authority,'READ_ONLY_HANDOFF_PLAN');
  assert.equal(plan.workspace_version,2);
  assert.equal(plan.canonical_episode_created,false);
  assert.equal(plan.production_started,false);
  assert.equal(plan.admission_granted,false);
  assert.equal(plan.model_calls,0);
  assert.equal(plan.runtime_writes,0);
  assert.equal(plan.items[0].server_draft_id,created.identity_map.drafts[draft.drafts[0].id]);
  assert.ok(plan.items[0].preflight_argv.includes('--dry-run'));
  const dryrunPath=url+'/preflight';
  const dryrunRequest={server_draft_id:plan.items[0].server_draft_id,
    workspace_version:plan.workspace_version,source_sha256:plan.source_sha256};
  const oldVersion=await fetchIt(dryrunPath,'POST',session2.session_token,session2.csrf_token,
    {...dryrunRequest,workspace_version:1});
  assert.equal(oldVersion.status,409);
  assert.equal((await oldVersion.json()).code,'PREFLIGHT_STALE_WORKSPACE');
  const csrfDenied=await fetchIt(dryrunPath,'POST',session2.session_token,undefined,dryrunRequest);
  assert.equal(csrfDenied.status,403);
  const badGet=await fetchIt(dryrunPath,'GET',session2.session_token);
  assert.equal(badGet.status,404);
  const readOnlyUnconfigured=await fetchIt(dryrunPath,'POST',session2.session_token,session2.csrf_token,dryrunRequest);
  assert.equal(readOnlyUnconfigured.status,503);
  assert.equal((await readOnlyUnconfigured.json()).code,'PREFLIGHT_READONLY_DB_NOT_CONFIGURED');
  assert.equal((await fetchIt(url+'/handoff-plan','POST',session2.session_token,session2.csrf_token,{})).status,404);
  const episodeDenied=await fetchIt(url+'/bootstrap','POST',session2.session_token,session2.csrf_token,
   {server_draft_id:plan.items[0].server_draft_id,workspace_version:2,
    source_sha256:plan.source_sha256,ack:'CREATE_EPISODE_WITHOUT_START'});
  assert.equal(episodeDenied.status,403);
  assert.equal((await episodeDenied.json()).code,'EPISODE_BOOTSTRAP_DISABLED');
  const index=(await (await fetchIt('','GET',session2.session_token)).json()).data.items;
  assert.ok(index.some(v=>v.workspace_id===created.workspace_id));
  assert.equal((await fetchIt('/session','DELETE',session2.session_token,session2.csrf_token)).status,200);
  assert.equal((await fetchIt('','GET',session2.session_token)).status,401);
 });
 await test('operator can revoke; unauthorized runtime and bootstrap remain unavailable',async()=>{
  assert.equal((await fetchIt('/runtime/start','POST',session.session_token,session.csrf_token,{})).status,404);
  assert.equal((await fetchIt('/session','DELETE',session.session_token,session.csrf_token)).status,200);
  assert.equal((await fetchIt('','GET',session.session_token)).status,401);
 });
}finally{await new Promise(done=>server.close(done));}
