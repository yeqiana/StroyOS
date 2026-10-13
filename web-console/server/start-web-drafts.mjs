import {resolve} from 'node:path';
import {WebDraftBridge} from './webDraftBridge.mjs';
import {createWebDraftServer,listenLocal} from './webDraftServer.mjs';

const testOnly=process.env.STORYOS_WEB_DRAFTS_TEST_ONLY==='1';
if(!testOnly&&process.env.STORYOS_WEB_DRAFTS_ENABLE!=='1')
 throw Error('Web draft Writer is disabled. Explicit permission required.');
const operatorToken=process.env.STORYOS_WEB_DRAFTS_OPERATOR_TOKEN;
if(!operatorToken||operatorToken.length<32)throw Error('Strong operator token required');
const port=Number(process.env.STORYOS_WEB_DRAFTS_PORT||19119);
const bridge=new WebDraftBridge({
 pythonExe:process.env.STORYOS_WEB_DRAFTS_PYTHON,
 authFile:process.env.STORYOS_WEB_DRAFTS_AUTH,
 root:resolve('.'),testOnly
});
const server=createWebDraftServer(bridge,{
 token:operatorToken,port,
 allowedBrowserOrigin:process.env.STORYOS_WEB_DRAFTS_BROWSER_ORIGIN,
 backend:testOnly?'mysql8_draft_canary':'mysql8_web_drafts'
});
await listenLocal(server,port);
console.log('StoryOS Web draft-only writer ready at loopback '+port+'. No canonical Episode or Driver capability.');
process.on('SIGINT',()=>server.close());
