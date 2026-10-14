import assert from 'node:assert/strict';
import {createMockAuthAdapter,MOCK_AUTH_STORAGE_KEY,DEFAULT_MOCK_PROFILE} from '../src/utils/mockAuth.ts';
const kv=new Map();
const store={
 getItem:key=>kv.get(key)??null,
 setItem:(key,value)=>{kv.set(key,value)},
 removeItem:key=>{kv.delete(key)},
};
const a=createMockAuthAdapter(store);
assert.equal(a.read().status,'guest');
const login=a.signIn();assert.equal(login.status,'mock');assert.equal(login.persistence,'saved');
assert.deepEqual(login.profile,DEFAULT_MOCK_PROFILE);
assert.equal(a.updateProfile({displayName:'  小说导演  ',avatar:'mountain'}).profile.displayName,'小说导演');
assert.equal(createMockAuthAdapter(store).read().profile.avatar,'mountain');
assert.equal(a.updateProfile({displayName:' ',avatar:'mountain'}).profile.displayName,'小说导演');
assert.equal(a.updateProfile({displayName:'导演',avatar:'invalid'}).profile.avatar,'mountain');
assert.equal(a.expire().status,'expired');
assert.equal(createMockAuthAdapter(store).read().status,'expired');
assert.equal(a.signOut().status,'guest');assert.equal(kv.has(MOCK_AUTH_STORAGE_KEY),false);
kv.set(MOCK_AUTH_STORAGE_KEY,JSON.stringify({version:1,kind:'storyos-mock-ui',status:'mock',profile:{displayName:'\nname',avatar:'book'}}));
assert.equal(createMockAuthAdapter(store).read().status,'guest','untrusted persisted content must fail closed');
kv.set(MOCK_AUTH_STORAGE_KEY,JSON.stringify({version:1,kind:'storyos-mock-ui',status:'admin',profile:{displayName:'admin',avatar:'book'},productionAuthorized:true}));
assert.equal(createMockAuthAdapter(store).read().status,'guest','unknown mock roles must be rejected');
const denied=createMockAuthAdapter({getItem(){throw Error('denied')},setItem(){throw Error('denied')},removeItem(){throw Error('denied')}});
assert.equal(denied.read().status,'guest');
assert.equal(denied.signIn().persistence,'session-only');
assert.equal(denied.updateProfile({displayName:'李明',avatar:'spark'}).persistence,'session-only');
assert.equal(denied.signOut().persistence,'session-only');
console.log('MOCK_AUTH_ADAPTER_CONTRACT_12_CASES_PASS');
