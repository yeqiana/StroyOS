import {spawnSync} from 'node:child_process';
import {readFileSync,existsSync} from 'node:fs';
import {resolve,dirname,join} from 'node:path';

const result=spawnSync('git',['rev-parse','--path-format=absolute','--git-common-dir'],{cwd:process.cwd(),encoding:'utf8',timeout:6000});
if(result.status!==0)throw Error('StoryOS Git common directory unavailable');
const root=dirname(resolve(result.stdout.trim()));
const dir=join(root,'.storyos-tmp','web-drafts');
const credential=join(dir,'web-draft-auth.json');
const tokenPath=join(dir,'web-draft-operator-token.txt');
const pythonPath=join(dir,'python-exe.txt');
if(!existsSync(credential)||!existsSync(tokenPath)||!existsSync(pythonPath))
 throw Error('Web drafts have not been explicitly provisioned');
const token=readFileSync(tokenPath,'utf8').trim();
if(token.length<32)throw Error('Invalid Web draft operator secret');
process.env.STORYOS_WEB_DRAFTS_ENABLE='1';
process.env.STORYOS_WEB_DRAFTS_TEST_ONLY='0';
process.env.STORYOS_WEB_DRAFTS_AUTH=credential;
process.env.STORYOS_WEB_DRAFTS_OPERATOR_TOKEN=token;
process.env.STORYOS_WEB_DRAFTS_PYTHON=readFileSync(pythonPath,'utf8').trim();
const readonly=join(dir,'preflight-mysql-readonly.json');
if(existsSync(readonly))process.env.STORYOS_WEB_DRAFTS_PREFLIGHT_AUTH=readonly;
await import('../web-console/server/start-web-drafts.mjs');
