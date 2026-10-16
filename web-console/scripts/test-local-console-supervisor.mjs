import assert from 'node:assert/strict';
import net from 'node:net';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {nextHealthMisses,restartWindow} from './local-console-supervisor-core.mjs';
const here=path.dirname(fileURLToPath(import.meta.url));
assert.equal(nextHealthMisses(0,false),1);
assert.equal(nextHealthMisses(2,false),3);
assert.equal(nextHealthMisses(3,true),0);
const now=Date.now();
assert.deepEqual(restartWindow([now-650000,now-30000,now-20000],now).history,[now-30000,now-20000]);
assert.equal(restartWindow([now-10000,now-9000,now-8000],now).allowed,false);
const owner=net.createServer((_socket)=>{});
await new Promise(resolve=>owner.listen(0,'127.0.0.1',resolve));
const occupied=owner.address().port;
try{
 const child=spawn(process.execPath,[path.join(here,'supervise-local-console.mjs')],{
  cwd:path.resolve(here,'..'),env:{...process.env,STORYOS_LOCAL_EVIDENCE_PORT:String(occupied),STORYOS_LOCAL_CONSOLE_PORT:'34178'},
  stdio:['ignore','pipe','pipe'],windowsHide:true,
 });
 let error='';
 child.stderr.on('data',chunk=>error+=chunk.toString());
 const status=await Promise.race([
   new Promise(resolve=>child.once('exit',(code)=>resolve({code}))),
   new Promise(resolve=>setTimeout(()=>resolve({timeout:true}),8000)),
 ]);
 if(status.timeout){child.kill();throw Error('supervisor failed to reject occupied port within 8 seconds')}
 assert.notEqual(status.code,0,'occupied port must reject duplicate supervisor');
 assert.match(error,/端口|占用/);
 assert.ok(owner.listening,'unrelated listener should survive');
 console.log('PASS supervisor: health failures, restart window and foreign-port protection');
}finally{owner.close()}