import assert from 'node:assert/strict';
import {resolveLocalPython} from './resolve-local-python.mjs';
const expected='C:\\Users\\alice\\AppData\\Local\\Programs\\Python\\Python312\\python.exe';
const fixture={platform:'win32',usersRoot:'C:\\Users',env:{LOCALAPPDATA:'C:\\Windows\\system32\\config\\systemprofile\\AppData\\Local'},
  readdirSync:()=>[{name:'alice',isDirectory:()=>true}],existsSync:x=>x===expected};
assert.equal(resolveLocalPython(fixture),expected);
assert.equal(resolveLocalPython({...fixture,env:{STORYOS_PYTHON:'D:\\python.exe'}}),'D:\\python.exe');
assert.equal(resolveLocalPython({platform:'linux',env:{}}),'python3');
assert.throws(()=>resolveLocalPython({...fixture,existsSync:()=>false}),/STORYOS_PYTHON/);
assert.throws(()=>resolveLocalPython({...fixture,readdirSync:()=>[{name:'alice',isDirectory:()=>true},{name:'bob',isDirectory:()=>true}],existsSync:()=>true}),/多个 Python/);
console.log('PASS Python resolver service profile / override / Linux / ambiguity');