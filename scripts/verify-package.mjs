/** Verify distributable resources without rewriting any fingerprint. */
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import assert from 'node:assert/strict';

const root=path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)),'..'));
const manifest=JSON.parse(await fs.readFile(path.join(root,'package.json'),'utf8'));
assert.equal(manifest.name,'dsh-ontology');
assert.equal(manifest.dsh?.bundle?.patch,'./cordis.patch.yml','DSH rc.5 requires an object with dsh.bundle.patch');
for(const item of ['lib/index.js','bridge/ontology_bridge.py','skills/ontology/SKILL.md','cordis.patch.yml','README.md','docs/PORTABILITY.md','THIRD_PARTY_NOTICES.md']) {
  assert((await fs.stat(path.join(root,item))).isFile(),`Missing package resource: ${item}`);
}
const entries=new Map();
for(const line of (await fs.readFile(path.join(root,'source-manifest.sha256'),'utf8')).trim().split(/\r?\n/)) {
  const match=/^([a-f0-9]{64})  (.+)$/.exec(line); assert(match,`Invalid manifest entry: ${line}`);
  const [,digest,file]=match; assert(!file.includes('..')&&!path.isAbsolute(file)&&!file.includes('\\'),`Unsafe manifest path: ${file}`);
  assert(!entries.has(file),`Duplicate manifest entry: ${file}`); entries.set(file,digest);
}
let files=0,bytes=0,jars=0,wheels=0;
async function walk(directory,relative='') {
  for(const item of await fs.readdir(directory,{withFileTypes:true})) {
    const name=relative ? `${relative}/${item.name}` : item.name;
    assert(!item.isSymbolicLink(),`Links cannot enter the package: ${name}`);
    assert(!['node_modules','__pycache__','.git','.venv','ontology-runs','history','archive'].includes(item.name),`Unexpected resource: ${name}`);
    if(item.isDirectory()) await walk(path.join(directory,item.name),name);
    else {
      assert(!/\.(?:json|pyc|pyo|log|tgz)$/i.test(name),`Unexpected native artifact: ${name}`);
      const data=await fs.readFile(path.join(directory,item.name));
      assert.equal(createHash('sha256').update(data).digest('hex'),entries.get(name),`Source fingerprint mismatch: ${name}`);
      files++;bytes+=data.length;if(name.endsWith('.jar'))jars++;if(name.endsWith('.whl'))wheels++;
    }
  }
}
await walk(path.join(root,'Ontology'));
assert.equal(files,entries.size,'Source file set differs'); assert.equal(jars,17);assert.equal(wheels,8);
const skills=(await fs.readdir(path.join(root,'Ontology','skills'),{withFileTypes:true})).filter(v=>v.isDirectory());
assert.equal(skills.length,9);
console.log(`Package verified: ${files} native files, ${bytes} bytes, ${skills.length+1} skills, ${jars} JARs, ${wheels} wheels.`);
