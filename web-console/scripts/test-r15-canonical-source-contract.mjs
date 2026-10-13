import assert from 'node:assert/strict';
import {projectCanonicalCatalog,matchCanonicalHistoricalEpisode} from '../src/api/canonicalCatalogProjection.ts';
const raw=(id,code,title)=>({
 episode_ref:id,business_episode_id:code,title,
 state_source:'local_workspace_episode_state_file',production_stage:'STORYBOARD_LOCKED'
});
const official=raw('LOCAL_1234567890abcdef12345678','09-05','婚礼前夜');
const another=raw('LOCAL_abcdef1234567890abcdef12','07-05','误入桃花源');
const response=items=>({items,count:items.length,total:items.length,has_more:false,errors:[],stage_counts:{},limit:100,offset:0});
const verified=projectCanonicalCatalog(response([official,another]));
assert.equal(verified.status,'complete');
assert.equal(verified.items.length,2);
assert.equal(verified.total,2);
assert.equal(verified.warning,null);
assert.equal(projectCanonicalCatalog({...response([official]),total:2}).status,'partial');
assert.equal(projectCanonicalCatalog({...response([official]),has_more:true}).status,'partial');
assert.equal(projectCanonicalCatalog({...response([official]),errors:['read_partial']}).status,'partial');
assert.equal(projectCanonicalCatalog(response([official,official])).items.length,1);
assert.equal(projectCanonicalCatalog(response([{...official,state_source:'isolated-test'}])).items.length,0);
assert.equal(projectCanonicalCatalog(response([{...official,episode_ref:'../fake'}])).items.length,0);
const idx=[
 {id:'ep-09-05',title:'婚礼前夜',code:'09-05'},
 {id:'ep-07-05',title:'误入桃花源',code:'07-05'},
 {id:'ep-home-one',title:'婚礼前夜',code:'09-05'},
];
assert.equal(matchCanonicalHistoricalEpisode(official,idx,[official,another])?.id,'ep-09-05');
assert.equal(matchCanonicalHistoricalEpisode({...official,title:'婚礼前夜改版'},idx,[official,another]),null);
assert.equal(matchCanonicalHistoricalEpisode(official,[...idx,idx[0]],[official,another]),null);
assert.equal(matchCanonicalHistoricalEpisode(official,idx,[official,official,another]),null);
assert.equal(matchCanonicalHistoricalEpisode({...official,business_episode_id:'07-05'},idx,[official,another]),null);
console.log('R15_REAL_RUNTIME_CATALOG_14_SOURCE_GUARDS_PASS');
