import assert from 'node:assert/strict';
import {detachLocalDraftProject as detach} from '../src/api/localDraftProject.ts';
const data=[
 {id:'ep-proj-1',projectId:'proj-delete',title:'Safe draft'},
 {id:'ep-proj-2',projectId:'proj-keep',title:'Other draft'},
 {id:'ep-10-01',projectId:'proj-delete',title:'Historical snapshot'},
 {id:'ep-home-3',projectId:'proj-delete',title:'Unusual home draft'}
];
const result=detach(data,'proj-delete');
assert.equal(result.length,4);
assert.equal(result[0].projectId,undefined);
assert.equal(result[1],data[1]);
assert.equal(result[2],data[2]);
assert.equal(result[3].projectId,undefined);
assert.equal(data[0].projectId,'proj-delete');
assert.deepEqual(detach(data,'nonexistent'),data);
console.log('SINGLE_NODE_PROJECT_DELETE_DRAFT_SAFETY_6_OF_6_PASS');
