// Round4 browser acceptance against isolated Vite build and loopback Chrome.
// No external runtime or Provider. Screenshot from the R3 live Chrome creation journey.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const suites=[
 ['create-reload-workbench','scripts/test-single-node-r3-browser.mjs',160000],
 ['five-offline-pages','scripts/test-console-journey.mjs',130000],
 ['readonly-recovery-failclosed','scripts/test-r33-recovery-safety.mjs',25000],
 ['historical-work-detail','scripts/test-episode-equivalence.mjs',25000],
];
for (const [name,script,timeout] of suites){
  const r=spawnSync(process.execPath,[script],{encoding:'utf8',timeout});
  process.stdout.write(r.stdout||'');
  process.stderr.write(r.stderr||'');
  assert.equal(r.status,0,'Round4 Chrome suite failed: '+name);
  console.log('SINGLE_NODE_R4_BROWSER_SUITE_PASS '+name);
}
console.log('SINGLE_NODE_R4_BROWSER_4_OF_4_PASS');
