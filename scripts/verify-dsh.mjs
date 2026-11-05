/** Actual DSH service registry + bundled Python/HermiT acceptance (no LLM). */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { realpathSync } from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { inspect } from 'node:util';
import os from 'node:os';

const usage = 'node scripts/verify-dsh.mjs [--plugin-root DIR] [--output NEW_DIR] [--python EXE] [--java EXE]\n'+
  'Defaults: this plugin root; a new directory in the system temp directory; ONTOLOGY_PYTHON or python; ONTOLOGY_JAVA or java.\n'+
  'Runs 26 checks using the installed real DSH SDK and local Python/HermiT. No LLM or external systems.\n';
const args = process.argv.slice(2), options = {};
for (let index=0; index<args.length; index++) {
  const key=args[index];
  if (key==='--help' || key==='-h') { console.log(usage); process.exit(0); }
  if (!['--plugin-root','--output','--python','--java'].includes(key) || !args[index+1]) throw new Error(usage);
  if (Object.hasOwn(options,key)) throw new Error('Duplicate argument: '+key);
  options[key]=args[++index];
}
const repo=path.resolve(options['--plugin-root'] ?? path.join(path.dirname(fileURLToPath(import.meta.url)),'..'));
const python=options['--python'] ?? process.env.ONTOLOGY_PYTHON ?? 'python';
const java=options['--java'] ?? process.env.ONTOLOGY_JAVA ?? 'java';
let out;
if (options['--output']) {
  out=path.resolve(options['--output']);
  out=path.join(await fs.realpath(path.dirname(out)),path.basename(out));
  const relative=path.relative(await fs.realpath(repo),out);
  assert(relative==='..' || relative.startsWith('..'+path.sep) || path.isAbsolute(relative),
    'Acceptance output must be outside the plugin installation');
  await fs.mkdir(out,{recursive:false});
} else out=await fs.mkdtemp(path.join(os.tmpdir(),'dsh-ontology-verification-'));
console.log('Acceptance evidence: '+out);
const workspace = path.join(out, '验收 项目');
const outside = path.join(out, 'outside');
await fs.mkdir(workspace); await fs.mkdir(outside);
const require = createRequire(path.join(repo, 'package.json'));
const toolsRequire = createRequire(realpathSync(require.resolve('@deepseek-ai/dsh-tools')));
const load = async (name, resolver = require) => import(pathToFileURL(resolver.resolve(name)));
const { Context } = await load('@deepseek-ai/cordis');
const { SystemPrompt } = await load('@deepseek-ai/dsh-system-prompt', toolsRequire);
const { ToolRuntime } = await load('@deepseek-ai/dsh-tools');
const { SkillRegistry } = await load('@deepseek-ai/dsh-skill');
const { default: LocalFileSystem } = await load('@deepseek-ai/dsh-fs-local');
const { default: LocalSubprocessRuntime } = await load('@deepseek-ai/dsh-subprocess-local');
const plugin = await import(pathToFileURL(path.join(repo, 'lib/index.js')));
const rows = [];
const ctx = new Context();
const mount = async (definition, config) => {
  const fiber = ctx.plugin(definition, config);
  await fiber.await();
  assert.equal(fiber.state, 2, 'Plugin did not activate');
};
async function check(name, action) {
  const start = performance.now();
  try {
    const result = await action();
    rows.push({ name, status: 'passed', seconds: ((performance.now()-start)/1000).toFixed(3) });
    await fs.writeFile(path.join(out, name+'.txt'), inspect(result, { depth: 12, maxStringLength: 100000 })+'\n');
    console.log(name+': passed');
    return result;
  } catch (error) {
    rows.push({ name, status: 'failed', seconds: ((performance.now()-start)/1000).toFixed(3) });
    await fs.writeFile(path.join(out, name+'.txt'), error.stack+'\n');
    console.error(name+': failed: '+error.message);
  }
}
async function call(name, args, code = undefined, rejected = false, signal = undefined) {
  const result = await ctx.tools.execute({callId:'acceptance-'+rows.length, name, arguments:args,
    signal:signal ?? new AbortController().signal});
  if (rejected) assert.equal(result.isError, true, inspect(result));
  else {
    assert.equal(result.isError, false, inspect(result));
    if (code !== undefined) assert.equal(result.value.exitCode, code, inspect(result));
    assert(result.content.some(block => block.type === 'text' && block.text.length > 0));
  }
  return result;
}
const operation = (stage, args, code=0) => call('ontology_run', {operation:stage,...args},code);
try {
  await mount(SystemPrompt);
  await mount(ToolRuntime);
  await mount(SkillRegistry);
  await mount(LocalFileSystem, {cwd:workspace});
  await mount(LocalSubprocessRuntime);
  // No agent/LLM session: the owner-selected directory is the only host fixture.
  ctx.provide('workingDirectory', {defaultDirectory:workspace});
  await mount(plugin, {pythonExecutable:python, javaExecutable:java,workspaceRoots:[workspace],timeoutSeconds:900});

  await check('01-registered-tools', async () => {
    const names=['ontology_environment','ontology_read_method','ontology_run','ontology_new_project'];
    for(const name of names) assert(ctx.tools.get(name));
    return names;
  });
  await check('02-all-skills-readable', async () => {
    const skills=await ctx.skills.list();
    const expected=(await fs.readdir(path.join(repo,'Ontology/skills'),{withFileTypes:true})).filter(v=>v.isDirectory()).length+1;
    assert.equal(skills.length, expected);
    for(const skill of skills) {
      const complete=await ctx.skills.get(skill.name);
      assert(complete.content.length>100); assert.equal(complete.provider,'dsh-ontology');
      assert.equal(complete.resourceBase.kind,'directory');
    }
    return skills;
  });
  await check('03-environment', async () => {
    const result=await call('ontology_environment',{});
    assert.equal(result.value.status,'ready'); assert.equal(result.value.javaReady,true);
    const nativeVersion=(await fs.readFile(path.join(repo,'Ontology/Ontology-tools/ontology_tools/__init__.py'),'utf8')).match(/__version__\s*=\s*["']([^"']+)/)?.[1];
    assert(nativeVersion); assert.equal(result.value.engineVersion,nativeVersion);
    return result;
  });
  await check('04-read-method', async () => {
    const result=await call('ontology_read_method',{path:'skills/ontology-builder/SKILL.md',limit:1000});
    assert(result.value.content.includes('ontology-builder')); return result;
  });
  await check('05-new-project-unicode-spaces', async () => {
    const result=await call('ontology_new_project',{destination:'ontology',example:'tagging'});
    assert.equal(result.value.status,'draft'); assert.equal(result.value.outputPath,path.join(workspace,'ontology'));
    return result;
  });
  await check('06-freeze',()=>operation('freeze',{package:'ontology'}));
  await check('07-inspect',()=>operation('inspect',{package:'ontology',output:'inspect'}));
  await check('08-infer-local',async()=>{
    const result=await operation('infer',{package:'ontology',output:'infer'});
    assert(result.value.artifacts.includes('closure.ttl')); assert(result.value.artifacts.includes('execution.ttl'));
    return result;
  });
  await fs.writeFile(path.join(workspace,'query.rq'),'SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 3\n');
  await check('09-query',()=>operation('query',{graph:'infer/closure.ttl',query:'query.rq',output:'query'}));
  await check('10-replay',()=>operation('replay',{run:'infer',output:'replay'}));
  await check('11-shacl-exit-3',()=>operation('validate',{package:'ontology',facts:['ontology/tests/inputs/invalid.ttl'],output:'shacl-invalid'},3));
  const model='@prefix ex: <https://example.org/dsh-acceptance#> .\n@prefix owl: <http://www.w3.org/2002/07/owl#> .\nex:A a owl:Class ; owl:disjointWith ex:B . ex:B a owl:Class . ex:a a owl:NamedIndividual,ex:A,ex:B .\n';
  await fs.writeFile(path.join(workspace,'inconsistent.ttl'),model);
  await check('12-owl-inconsistent-exit-1',()=>operation('owl-dl',{ontology:['inconsistent.ttl'],output:'owl-inconsistent'},1));
  await fs.writeFile(path.join(workspace,'malformed.ttl'),'this is not Turtle');
  await check('13-technical-exit-2',()=>operation('owl-dl',{ontology:['malformed.ttl'],output:'technical-failure'},2));
  await check('14-formula-project',()=>call('ontology_new_project',{destination:'formula ontology',example:'formula'}));
  await check('15-formula-freeze',()=>operation('freeze',{package:'formula ontology'}));
  await check('16-formula-infer-real-hermit',()=>operation('infer',{package:'formula ontology',output:'formula infer'}));
  await check('17-formula-golden-real-hermit',()=>operation('test',{package:'formula ontology',output:'formula test'}));
  await check('18-formula-replay-real-hermit',()=>operation('replay',{run:'formula infer',output:'formula replay'}));

  await fs.writeFile(path.join(outside,'model.ttl'),model);
  await check('19-outside-input-rejected',()=>call('ontology_run',{operation:'owl-dl',ontology:[path.join(outside,'model.ttl')],output:'outside-read'},undefined,true));
  await check('20-output-traversal-rejected',()=>call('ontology_run',{operation:'inspect',package:'ontology',output:'../outside/result'},undefined,true));
  await fs.symlink(outside,path.join(workspace,'outside-junction'),'junction');
  await check('21-junction-escape-rejected',()=>call('ontology_run',{operation:'owl-dl',ontology:['outside-junction/model.ttl'],output:'junction-read'},undefined,true));
  await check('22-method-traversal-rejected',()=>call('ontology_read_method',{path:'../README.md'},undefined,true));
  await check('23-existing-output-rejected',()=>call('ontology_run',{operation:'infer',package:'ontology',output:'infer'},undefined,true));
  await check('24-cancelled-before-dispatch',()=>call('ontology_run',{operation:'infer',package:'ontology',output:'cancelled'},undefined,true,AbortSignal.abort()));
  await check('25-package-write-rejected',()=>call('ontology_run',{operation:'freeze',package:path.join(repo,'Ontology/Ontology-tools/examples/tagging')},undefined,true));
  await check('26-no-evidence-from-rejected-calls',async()=>{
    for(const name of ['outside-read','junction-read','cancelled']) await assert.rejects(fs.stat(path.join(workspace,name)),{code:'ENOENT'});
    await assert.rejects(fs.stat(path.join(outside,'result')),{code:'ENOENT'});
    return 'No rejected operation wrote evidence.';
  });
} catch (error) {
  rows.push({name:'setup-or-fixture-failure',status:'failed',seconds:'0'});
  await fs.writeFile(path.join(out,'setup-or-fixture-failure.txt'),error.stack+'\n');
  console.error(error);
} finally {
  await ctx.fiber.dispose();
  const failed=rows.filter(row=>row.status!=='passed');
  const passed=failed.length===0 && rows.length===26;
  await fs.writeFile(path.join(out,'acceptance.md'),
    '# DSH SDK registration and execution acceptance\n\n'+
    `Result: **${passed?'passed':'failed'}**; ${rows.length-failed.length}/26 checks.\n\n`+
    'Uses actual Cordis, ToolRuntime, SystemPrompt, SkillRegistry, LocalFileSystem, LocalSubprocessRuntime, the built plugin, and bundled Python/HermiT. '+
    'Only workingDirectory.defaultDirectory is a host fixture; no agent session, UI, online model, OCR, or business-model quality is tested.\n\n'+
    '| Check | Result | Seconds |\n|---|---|---:|\n'+rows.map(r=>`| ${r.name} | ${r.status} | ${r.seconds} |`).join('\n')+'\n');
  console.log(`SDK verification: ${passed?'passed':'failed'} (${rows.length-failed.length}/26). Evidence: ${out}`);
  process.exitCode=passed?0:1;
}
