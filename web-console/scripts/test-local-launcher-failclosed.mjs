import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const worker=spawn(process.execPath,[path.join(here,'launch-local-real-console.mjs')],{
  cwd:path.resolve(here,'..'),
  env:{...process.env,STORYOS_PYTHON:process.execPath,STORYOS_LOCAL_EVIDENCE_PORT:'34179',STORYOS_LOCAL_CONSOLE_PORT:'34180'},
  stdio:['ignore','pipe','pipe'],windowsHide:true,
});
let last='';
worker.stderr.on('data',b=>last+=b.toString().slice(0,1000));
const result=await Promise.race([
 new Promise(resolve=>worker.once('exit',(code)=>resolve({code}))),
 new Promise(resolve=>setTimeout(()=>resolve({timeout:true}),9500)),
]);
if(result.timeout){worker.kill();throw Error('failed Python child left launcher Job alive (zombie startup)')}
assert.notEqual(result.code,0,'invalid API Python must fail and stop parent');
console.log('PASS launcher: failed API child forces prompt nonzero parent exit');