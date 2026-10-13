import assert from 'node:assert/strict';
import {createDraftBackup,reviewDraftRestore,MAX_BACKUP_CHARS} from '../src/api/localDraftBackup.ts';

const draft=(id='ep-home-12345',projectId='proj-1730000000000')=>({
 id,title:'可迁移本地草稿',code:'LOCAL-123',synopsis:'来自浏览器',projectId,
 currentStage:'IDEA_LOCK',storyboardBeats:[],characters:[],frameReviews:[],
 preflightChecks:[],runtimeRequest:{imageModel:'gpt-image-2'}
});
const project={id:'proj-1730000000000',name:'迁移专用项目',createdAt:'2026-10-13',episodeIds:['ep-home-12345']};
const data=createDraftBackup([draft(),{...draft(),id:'ep-09-05'}],[project]);
assert.equal(data.source,'browser_local_only');
assert.equal(data.drafts.length,1);
const json=JSON.stringify(data);
const good=reviewDraftRestore(json,[],[]);
assert.equal(good.ok,true);assert.equal(good.draftCount,1);assert.equal(good.projectCount,1);
assert.equal(reviewDraftRestore(json,[draft()],[]).ok,false,'same draft id never overwrite');
assert.equal(reviewDraftRestore(json,[],[project]).ok,false,'same project id never overwrite');
assert.equal(reviewDraftRestore('{broken',[],[]).ok,false);
assert.equal(reviewDraftRestore('x'.repeat(MAX_BACKUP_CHARS+1),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,version:2}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,source:'production'}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,drafts:[draft(),draft()]}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,drafts:[{...draft(),id:'ep-09-05'}]}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,drafts:[{...draft(),projectId:'missing'}]}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,projects:[{...project,episodeIds:['ok',5]}]}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,projects:[{...project,name:''}]}),[],[]).ok,false);
assert.equal(reviewDraftRestore(JSON.stringify({...data,drafts:[{...draft(),title:'x'.repeat(221)}]}),[],[]).ok,false);
const oldEpisode={...draft(),id:'ep-home-old'};
const merged=reviewDraftRestore(json,[oldEpisode],[]);
assert.equal(merged.ok,true);
assert.equal(merged.addedDrafts.length,1);
assert.equal(oldEpisode.id,'ep-home-old');
console.log('R16_LOCAL_DRAFT_BACKUP_RESTORE_16_GUARDS_PASS');
