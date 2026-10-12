import assert from 'node:assert/strict';

// This is deliberately restricted to the explicit local read-only StoryOS console.
// Never target a production endpoint or send a production action in this test.
const base='http://127.0.0.1:3100';
const fetchLocal=async(path,options={})=>fetch(base+path,{...options,signal:AbortSignal.timeout(12000)});
const statuses=await fetchLocal('/api/v1/runtime/statuses?limit=1&offset=0');
assert.equal(statuses.status,200);
const snapshot=await statuses.json();
assert.equal(snapshot.code,'OK');
assert.ok(snapshot.data?.total>0,'local read-only evidence must contain real states');
assert.equal(snapshot.data.items[0]?.state_source,'local_workspace_episode_state_file');
console.log('PASS status evidence: local disk source, '+snapshot.data.total+' real records');

const catalog=await fetchLocal('/api/v1/local-media/catalog');
assert.equal(catalog.status,200);
const assets=await catalog.json();
assert.equal(assets.data?.source,'local_workspace_approved_only');
const first=assets.data.items?.find(item=>item.frames?.length)?.frames?.[0]?.url;
assert.ok(first?.startsWith('/api/v1/local-media/images/'),'only canonical approved images can be served');
const image=await fetchLocal(first);
assert.equal(image.status,200);
assert.ok(image.headers.get('content-type')?.startsWith('image/'),'real approved picture MIME expected');
assert.equal(image.headers.get('cache-control'),'no-store');
console.log('PASS approved media: canonical token, true image response, no-store cache');

const events=await fetchLocal('/api/v1/events');
assert.equal(events.status,403,'unregistered event stream must fail closed');
const agents=await fetchLocal('/api/v1/agents');
assert.equal(agents.status,403,'unregistered Agent API must fail closed');
console.log('PASS unsupported APIs: events and Agent Registry explicitly denied');

const denied=await fetchLocal('/api/v1/runtime/statuses',{method:'POST',headers:{'content-type':'application/json'},body:'{}'});
assert.equal(denied.status,403,'local runtime must not allow state mutations');
const cross=await fetchLocal('/api/v1/local-media/catalog',{headers:{Origin:'https://outside.example.invalid'}});
assert.equal(cross.status,403,'foreign origin must not read local episode media');
console.log('PASS authorization: writes and cross-origin asset reads denied');

console.log('R32_LOCAL_READONLY_SAFETY_5_OF_5_PASS');
