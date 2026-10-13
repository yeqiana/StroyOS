import {resolve} from 'node:path';
import {IsolatedDraftStore} from './draftStore.mjs';
import {TestMysqlBridge} from './testMysqlBridge.mjs';
import {createDraftMutationServer,listenLocal} from './draftMutationServer.mjs';
if(process.env.STORYOS_R17_TEST_ONLY!=='1')throw new Error('Production mode forbidden');
const port=Number(process.env.STORYOS_R17_PORT||19118),token=process.env.STORYOS_R17_OPERATOR_TOKEN;
if(!token||token.length<32)throw new Error('Strong operator secret required before any data access');
const mode=process.env.STORYOS_R17_BACKEND;
if(mode!=='mysql8-test-only'&&mode!=='sqlite-test-only')throw new Error('Explicit isolated storage backend required');
const store=mode==='mysql8-test-only'
 ?new TestMysqlBridge({
   pythonExe:process.env.STORYOS_R17_PYTHON,
   credentialFile:process.env.STORYOS_R17_MYSQL_TEST_AUTH,
   root:resolve('.'),
  })
 :new IsolatedDraftStore(resolve('.storyos-tmp/r17-test-only/draft-vault.sqlite'),{testOnly:true});
const server=createDraftMutationServer(store,{token,port,
 allowedBrowserOrigin:process.env.STORYOS_R17_BROWSER_ORIGIN,
 backend:mode==='mysql8-test-only'?'mysql8_test_only':'sqlite_test_only'});
await listenLocal(server,port);
console.log('StoryOS R17 '+mode+' (TEST_ONLY) on loopback '+port+', no canonical Writer');
process.on('SIGINT',()=>{server.close();store.close?.();});
