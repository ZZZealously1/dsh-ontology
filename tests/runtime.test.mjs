import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { spawn } from 'node:child_process';
import { createOntologyRuntime, engineRoot, pluginRoot } from '../src/runtime.ts';

const base = process.env.ONTOLOGY_PLUGIN_TEST_OUTPUT || path.join(os.tmpdir(), 'dsh-ontology-tests');
await fs.mkdir(base, {recursive:true});
const root = await fs.mkdtemp(path.join(base, 'runtime-'));
const outside = await fs.mkdtemp(path.join(base, 'outside-'));
const context = {cwd:root, signal:new AbortController().signal};
let calls = 0;
const fake = async () => { calls++; return {exitCode:0,stdout:'{"status":"passed"}',stderr:''}; };
const runtime = createOntologyRuntime({workspaceRoots:[root]}, fake);
const bundled = path.join(engineRoot, 'examples', 'tagging');

test('method library supports bounded reads without project configuration', async () => {
  const rt = createOntologyRuntime({workspaceRoots:[]}, fake);
  const first = await rt.readMethod({limit:30});
  assert.equal(first.content.length,30); assert.equal(first.nextOffset,30);
  assert.equal((await rt.readMethod({offset:30,limit:30})).offset,30);
  await assert.rejects(rt.run({operation:'inspect'},context), /workspaceRoot/);
  await assert.rejects(rt.newProject({example:'tagging',destination:'ontology'},context), /workspaceRoot/);
});
test('method traversal, executable resources and invalid slices are rejected', async () => {
  await assert.rejects(runtime.readMethod({path:'../package.json'}), /escapes/);
  await assert.rejects(runtime.readMethod({path:pluginRoot}), /relative/);
  await assert.rejects(runtime.readMethod({offset:-1}), /slice/);
  await assert.rejects(runtime.readMethod({limit:64001}), /slice/);
});
test('outside input and output paths never reach a subprocess', async () => {
  const count=calls;
  await assert.rejects(runtime.run({operation:'inspect',package:outside,output:'outside-input'},context), /outside/);
  await assert.rejects(runtime.run({operation:'inspect',package:bundled,output:path.join(outside,'out')},context), /outside/);
  assert.equal(calls,count);
});
test('installation writes are rejected even when its parent is an allowed workspace', async () => {
  const rt=createOntologyRuntime({workspaceRoots:[path.dirname(pluginRoot)]},fake);
  await assert.rejects(rt.run({operation:'freeze',package:bundled},context), /installation/);
  await assert.rejects(rt.newProject({example:'tagging',destination:path.join(pluginRoot,'draft')},context), /installation/);
});
test('directory junction escapes are rejected before read or write', async () => {
  const link=path.join(root,'redirect');
  await fs.symlink(outside,link,process.platform==='win32'?'junction':'dir');
  await assert.rejects(runtime.run({operation:'inspect',package:link,output:'link-read'},context), /outside/);
  await assert.rejects(runtime.run({operation:'inspect',package:bundled,output:path.join(link,'new')},context), /outside/);
});
test('operation allowlist and structured argument restrictions cannot become arbitrary commands', async () => {
  await assert.rejects(runtime.run({operation:'shell'},context), /Unsupported/);
  await assert.rejects(runtime.run({operation:'inspect',package:bundled,output:'extra',java:'evil'},context), /Unexpected/);
  await assert.rejects(runtime.run({operation:'infer',package:bundled,output:'facts',facts:[]},context), /exactly one/);
  await assert.rejects(runtime.run({operation:'owl-dl',ontology:[path.join(bundled,'ontology.ttl')],output:'timeout',javaTimeout:0},context), /javaTimeout/);
});
test('draft copy excludes manifests and does not overwrite existing destinations', async () => {
  const result=await runtime.newProject({destination:'ontology',example:'tagging'},context);
  assert.equal(result.status,'draft');
  assert.ok((await fs.readFile(path.join(result.outputPath,'ontology.ttl'),'utf8')).length);
  await assert.rejects(fs.access(path.join(result.outputPath,'manifest.sha256')));
  await assert.rejects(runtime.newProject({destination:'ontology',example:'tagging'},context), /exists/);
  await assert.rejects(runtime.run({operation:'inspect',package:bundled,output:'ontology'},context), /exists/);
});
test('already cancelled calls do not run the child', async () => {
  const count=calls;
  await assert.rejects(runtime.run({operation:'inspect',package:bundled,output:'cancel'}, {...context,signal:AbortSignal.abort()}));
  assert.equal(calls,count);
});
test('malformed bridge output is rejected, not interpreted as semantic success', async () => {
  const rt=createOntologyRuntime({workspaceRoots:[root]}, async()=>({exitCode:0,stdout:'not a response',stderr:''}));
  await assert.rejects(rt.environment(context),/valid response/);
});

// These integration tests always run. Missing Python/Java is a failure, not a skip.
const python=process.env.ONTOLOGY_PYTHON || 'python';
const java=process.env.ONTOLOGY_JAVA || 'java';
const nativeRunner = spec => new Promise((resolve,reject)=>{
  const child=spawn(spec.command,spec.args,{cwd:spec.cwd,env:{...process.env,...spec.env},windowsHide:true,signal:spec.signal});
  let stdout='',stderr='';
  child.stdout.on('data',data=>stdout+=data); child.stderr.on('data',data=>stderr+=data);
  child.on('error',reject); child.on('close',exitCode=>resolve({exitCode,stdout,stderr}));
});
const real=createOntologyRuntime({workspaceRoots:[root],pythonExecutable:python,javaExecutable:java},nativeRunner);
test('bridge environment confirms real Python, dependency fingerprints and Java', async()=>{
  const result=await real.environment(context);
  assert.equal(result.status,'ready',JSON.stringify(result));
  assert.equal(result.engineVersion,'0.4.0'); assert.equal(result.javaReady,true);
});
test('native inference, query and replay preserve their artifacts and success', async()=>{
  const result=await real.run({operation:'infer',package:bundled,output:'infer'},context);
  assert.equal(result.exitCode,0,result.summary); assert.equal(result.status,'passed');
  assert.ok(result.artifacts.includes('trace.ttl')); assert.ok(result.artifacts.includes('closure.ttl'));
  const queryFile=path.join(root,'query.rq'); await fs.writeFile(queryFile,'SELECT ?s WHERE { ?s a <https://example.org/ontology-template/demo#TaggedItem> }');
  const query=await real.run({operation:'query',graph:path.join(result.outputPath,'closure.ttl'),query:queryFile,output:'query'},context);
  assert.equal(query.exitCode,0,query.summary);
  const replay=await real.run({operation:'replay',run:result.outputPath,output:'replay'},context);
  assert.equal(replay.exitCode,0,replay.summary);
});
test('SHACL mismatch remains exit 3, distinct from malformed-data exit 2', async()=>{
  const invalid=path.join(root,'invalid.ttl');
  await fs.writeFile(invalid,'@prefix ex: <https://example.org/ontology-template/demo#> . ex:missing a ex:Item .');
  const shacl=await real.run({operation:'validate',package:bundled,facts:[invalid],output:'invalid-shacl'},context);
  assert.equal(shacl.exitCode,3,shacl.summary);
  const malformed=path.join(root,'malformed.ttl'); await fs.writeFile(malformed,'THIS IS NOT TURTLE');
  const technical=await real.run({operation:'validate',package:bundled,facts:[malformed],output:'malformed-data'},context);
  assert.equal(technical.exitCode,2,technical.summary);
});
test('OWL inconsistency is a completed nonconformant semantic check', async()=>{
  const ontology=path.join(root,'contradiction.ttl');
  await fs.writeFile(ontology,'@prefix owl: <http://www.w3.org/2002/07/owl#> . <urn:example:i> a owl:NamedIndividual, owl:Nothing .');
  const result=await real.run({operation:'owl-dl',ontology:[ontology],output:'owl-inconsistent'},context);
  assert.equal(result.exitCode,1,result.summary); assert.equal(result.status,'nonconformant');
  assert.equal(result.semanticState,'inconsistent');
});
test('package and replay metadata cannot select an arbitrary executable', async()=>{
  const draft=await real.newProject({destination:'bad-executable',example:'tagging'},context);
  await fs.appendFile(path.join(draft.outputPath,'runtime.ttl'),'\n<urn:bad> <https://w3id.org/ontology-tools#javaExecutable> "untrusted-executable" .\n');
  const first=await real.run({operation:'infer',package:draft.outputPath,output:'bad-java'},context);
  assert.equal(first.exitCode,2); assert.match(first.summary,/trusted plugin/);
  const replay=path.join(root,'fake-replay'); await fs.mkdir(replay);
  await fs.writeFile(path.join(replay,'execution.ttl'),'<urn:ontology-tools:run> <https://w3id.org/ontology-tools#javaExecutable> "untrusted-executable" .');
  const second=await real.run({operation:'replay',run:replay,output:'bad-replay-java'},context);
  assert.equal(second.exitCode,2); assert.match(second.summary,/trusted plugin/);
});
test('SPARQL SERVICE is refused before network execution',async()=>{
  const queryFile=path.join(root,'service.rq'); await fs.writeFile(queryFile,'SELECT * WHERE { SERVICE <http://127.0.0.1:9/> { ?s ?p ?o } }');
  const result=await real.run({operation:'query',graph:path.join(bundled,'ontology.ttl'),query:queryFile,output:'service'},context);
  assert.equal(result.exitCode,2); assert.match(result.summary,/SERVICE|remote|network/i);
});
test('package metadata cannot be read through an internal directory junction',async()=>{
  const draft=await real.newProject({destination:'linked-package',example:'tagging'},context);
  await fs.writeFile(path.join(outside,'runtime.ttl'),'THIS CONTENT MUST NOT BE PARSED');
  await fs.symlink(outside,path.join(draft.outputPath,'linked'),process.platform==='win32'?'junction':'dir');
  const result=await real.run({operation:'infer',package:draft.outputPath,output:'linked-run'},context);
  assert.equal(result.exitCode,2); assert.match(result.summary,/Links|escapes/);
  assert.doesNotMatch(result.summary,/THIS CONTENT/);
});
test('host Java option injection is removed from the reasoning subprocess environment',async()=>{
  const saved=process.env.JAVA_TOOL_OPTIONS;
  process.env.JAVA_TOOL_OPTIONS='--a-deliberately-invalid-option';
  try { assert.equal((await real.environment(context)).status,'ready'); }
  finally { if(saved===undefined) delete process.env.JAVA_TOOL_OPTIONS; else process.env.JAVA_TOOL_OPTIONS=saved; }
});
