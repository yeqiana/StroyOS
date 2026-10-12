// Real offline Chrome QA: static sandbox server + existing local draft CDP journey.
// Deliberately no backend access, no paid Provider, no data writes outside isolated Chrome profile.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
const dist=path.resolve('dist');
assert.ok(fs.existsSync(path.join(dist,'index.html')),'Build the isolated Vite dist first');
const server=spawn(process.execPath,['scripts/test-static-server.mjs',dist],{stdio:['ignore','pipe','pipe']});
let port;
try {
  port=await new Promise((resolve,reject)=>{
    let output='';
    const timer=setTimeout(()=>reject(Error('isolated server not ready')),12000);
    server.stdout.on('data',buf=>{output+=buf.toString();const m=output.match(/READY (\d+)/);if(m){clearTimeout(timer);resolve(Number(m[1]))}});
    server.on('error',reject);
    server.on('exit',code=>reject(Error('static server exited early '+code)));
  });
  assert.ok(Number.isInteger(port)&&port>0);
  const env={...process.env,STORYOS_LOCAL_CONSOLE_URL:'http://127.0.0.1:'+port+'/'};
  const result=spawnSync(process.execPath,['scripts/test-r32-local-draft-browser.mjs','--width=1440'],
    {cwd:process.cwd(),env,encoding:'utf8',timeout:160000});
  process.stdout.write(result.stdout||'');
  process.stderr.write(result.stderr||'');
  assert.equal(result.status,0,'actual Chrome local draft create/reload/editor click must pass');
  console.log('SINGLE_NODE_R3_REAL_CHROME_CREATE_RESTORE_1_OF_1_PASS');
} finally {server.kill();}
