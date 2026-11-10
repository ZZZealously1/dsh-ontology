import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { Context } from '@deepseek-ai/cordis';
import SandboxedFileSystem from '@deepseek-ai/dsh-fs-sandbox';
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local';
import { assertLocalExecution, createDshProcessRunner, createDshProjectWriter, resolveOntologyCallContext } from '../lib/index.js';
import { createOntologyRuntime, engineRoot } from '../src/runtime.ts';

async function host(t, mode = 'workspace-write') {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(),'ontology-sandbox-test-'));
  const ctx = new Context();
  const policy = {mode,workspaceRoot:directory,sessionId:'synthetic-session'};
  ctx.provide('sandboxPolicy',{defaultMode:mode,resolve(){return {...policy};}});
  await ctx.plugin(SandboxedFileSystem,{}).await();
  await ctx.plugin(LocalSubprocessRuntime).await();
  t.after(async()=>{
    await ctx.fiber.dispose();
    // Own temporary directory, resolved before recursive cleanup.
    assert.equal(path.dirname(directory),await fs.realpath(os.tmpdir()));
    await fs.rm(directory,{recursive:true,force:true});
  });
  return {ctx,directory,policy};
}
const call = directory => ({cwd:directory,signal:new AbortController().signal});
const spec = (directory,script='console.log("unwrapped")') => ({command:process.execPath,args:['-e',script],cwd:directory,
  signal:new AbortController().signal,timeoutMs:10000,maxOutputBytes:65536});
const bridge = async()=>({exitCode:0,stdout:'{"status":"passed"}',stderr:''});
const wrapped = script => ({argv:[process.execPath,'-e',script],enforcement:'partial',denialSignatures:['synthetic denied'],
  runnerFailureRules:[{allowedExitCodes:[71],fatalSignatures:['synthetic runner unavailable']}]});

test('known sandbox filesystem is accepted without changing default host providers',async t=>{
  const {ctx}=await host(t);
  assert.doesNotThrow(()=>assertLocalExecution(ctx));
});
test('calling session is passed to the sandbox policy owner; effective cwd never widens its boundary',async t=>{
  const ctx=new Context();t.after(()=>ctx.fiber.dispose());
  const directory=process.cwd();
  const session={header:{cwd:directory}};
  const policy={mode:'read-only',workspaceRoot:directory,sessionId:'calling-session'};
  ctx.provide('sandboxPolicy',{resolve(request){assert.equal(request.session,session);return policy;}});
  const result=await resolveOntologyCallContext(ctx,{agent:{session},signal:new AbortController().signal});
  assert.deepEqual(result.sandboxPolicy,policy);
});
test('an invalid policy owner cannot silently degrade into unconfined execution',async t=>{
  const ctx=new Context();t.after(()=>ctx.fiber.dispose());
  ctx.provide('sandboxPolicy',{resolve(){return undefined;}});
  await assert.rejects(resolveOntologyCallContext(ctx,{signal:new AbortController().signal}),/invalid sandbox policy/);
});
test('project scaffold writes use the real DSH filesystem and refuse overwrite',async t=>{
  const {ctx,directory,policy}=await host(t);
  const runtime=createOntologyRuntime({workspaceRoots:[directory]},bridge,createDshProjectWriter(ctx));
  const result=await runtime.newProject({destination:'ontology',example:'tagging'},{...call(directory),sandboxPolicy:policy});
  assert.match(await fs.readFile(path.join(result.outputPath,'ontology.ttl'),'utf8'),/owl:/);
  await assert.rejects(fs.access(path.join(result.outputPath,'manifest.sha256')));
  await assert.rejects(runtime.newProject({destination:'ontology',example:'tagging'},{...call(directory),sandboxPolicy:policy}),/exists/);
});
test('read-only policy denies scaffold and inference report writes before any dispatch',async t=>{
  const {ctx,directory,policy}=await host(t,'read-only');
  let dispatched=0;
  const runtime=createOntologyRuntime({workspaceRoots:[directory]},async()=>{dispatched++;return bridge();},createDshProjectWriter(ctx));
  const context={...call(directory),sandboxPolicy:policy};
  await assert.rejects(runtime.newProject({destination:'ontology',example:'tagging'},context),/read-only/);
  await assert.rejects(runtime.run({operation:'inspect',package:path.join(engineRoot,'examples','tagging'),output:'run'},context),/read-only/);
  assert.equal(dispatched,0);
  assert.deepEqual(await fs.readdir(directory),[]);
});
test('a broad configured workspace cannot override the narrower calling session sandbox',async t=>{
  const {ctx,directory,policy}=await host(t);
  const inner=path.join(directory,'session'); await fs.mkdir(inner);
  const runtime=createOntologyRuntime({workspaceRoots:[directory]},bridge,createDshProjectWriter(ctx));
  await assert.rejects(runtime.newProject({destination:'../sibling',example:'tagging'},
    {...call(inner),sandboxPolicy:{...policy,workspaceRoot:inner}}),/session sandbox/);
  await assert.rejects(fs.access(path.join(directory,'sibling')));
});
test('runtime never falls back to raw project writes when the host writer is absent',async t=>{
  const {directory}=await host(t);
  const runtime=createOntologyRuntime({workspaceRoots:[directory]},bridge);
  await assert.rejects(runtime.newProject({destination:'ontology',example:'tagging'},call(directory)),/host filesystem writer/);
  assert.deepEqual(await fs.readdir(directory),[]);
});
test('missing process sandbox fails closed before the requested child can write',async t=>{
  const {ctx,directory}=await host(t);
  const file=path.join(directory,'must-not-exist');
  await assert.rejects(createDshProcessRunner(ctx)(spec(directory,`require('node:fs').writeFileSync(${JSON.stringify(file)},'bad')`)),error=>error.code==='SANDBOX_UNAVAILABLE');
  await assert.rejects(fs.access(file));
});
test('confine failure is never retried using the original unconfined argv',async t=>{
  const {ctx,directory}=await host(t);
  let calls=0;
  ctx.provide('sandbox',{async confine(){calls++;throw new Error('fixture confinement unavailable');}});
  await assert.rejects(createDshProcessRunner(ctx)(spec(directory)),/fixture confinement unavailable/);
  assert.equal(calls,1);
});
test('only wrapped argv is spawned and its partial enforcement is reported honestly',async t=>{
  const {ctx,directory,policy}=await host(t);
  const original=spec(directory);
  ctx.provide('sandbox',{async confine(argv,receivedPolicy,signal){
    assert.deepEqual(argv,[await fs.realpath(process.execPath),...original.args]);
    assert.deepEqual(receivedPolicy,policy);assert.ok(signal instanceof AbortSignal);
    return wrapped('console.log("confined fixture")');
  }});
  const result=await createDshProcessRunner(ctx)(original);
  assert.equal(result.stdout.trim(),'confined fixture');
  assert.deepEqual(result.sandbox,{mode:'workspace-write',enforcement:'partial'});
});
test('explicit host danger-full-access policy can run locally without fabricating confinement',async t=>{
  const {ctx,directory}=await host(t,'danger-full-access');
  const result=await createDshProcessRunner(ctx)(spec(directory));
  assert.equal(result.stdout.trim(),'unwrapped');
  assert.deepEqual(result.sandbox,{mode:'danger-full-access'});
});
test('runner infrastructure failure remains distinct from sandbox denial',async t=>{
  const {ctx,directory}=await host(t);
  const release=ctx.provide('sandbox',{async confine(){return wrapped('console.error("synthetic runner unavailable");process.exitCode=71');}});
  await assert.rejects(createDshProcessRunner(ctx)(spec(directory)),error=>error.code==='SANDBOX_UNAVAILABLE');
  await release();
  ctx.provide('sandbox',{async confine(){return wrapped('console.error("synthetic denied");process.exitCode=1');}});
  await assert.rejects(createDshProcessRunner(ctx)(spec(directory)),/sandbox denied/);
});
