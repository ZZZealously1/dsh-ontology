import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { Context } from '@deepseek-ai/cordis';
import LocalFileSystem from '@deepseek-ai/dsh-fs-local';
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local';
import { assertLocalExecution, createDshProcessRunner } from '../lib/index.js';

async function host(t, subprocess = LocalSubprocessRuntime) {
  const ctx = new Context();
  await ctx.plugin(LocalFileSystem, {}).await();
  await ctx.plugin(subprocess).await();
  assert.ok(ctx.fs && ctx.subprocess, 'real DSH providers must be mounted');
  t.after(() => ctx.fiber.dispose());
  return ctx;
}

function spec(script, changes = {}) {
  return { command: process.execPath, args: ['-e', script], cwd: process.cwd(),
    signal: new AbortController().signal, timeoutMs: 10000, maxOutputBytes: 65536, ...changes };
}

test('real DSH subprocess returns exit facts and bounded stdout/stderr without a shell', async t => {
  const runner = createDshProcessRunner(await host(t));
  const result = await runner(spec('console.log(process.env.ONTOLOGY_TEST);console.error("diagnostic");process.exitCode=7',
    { env: { ONTOLOGY_TEST: 'literal & $() ; text' } }));
  assert.equal(result.exitCode, 7);
  assert.equal(result.stdout.trim(), 'literal & $() ; text');
  assert.equal(result.stderr.trim(), 'diagnostic');
});

test('real DSH subprocess rejects truncated protocol output', async t => {
  const runner = createDshProcessRunner(await host(t));
  await assert.rejects(runner(spec('process.stdout.write("x".repeat(10000))', { maxOutputBytes: 128 })), /capture limit/);
});

test('real DSH subprocess cancellation drains the managed process range', async t => {
  const runner = createDshProcessRunner(await host(t));
  const controller = new AbortController();
  const running = runner(spec('setInterval(()=>{},1000)', { signal: controller.signal }));
  const timer = setTimeout(() => controller.abort(new Error('caller cancelled')), 150);
  t.after(() => clearTimeout(timer));
  await assert.rejects(running, /caller cancelled/);
});

test('real DSH subprocess timeout is a technical failure', async t => {
  const runner = createDshProcessRunner(await host(t));
  await assert.rejects(runner(spec('setInterval(()=>{},1000)', { timeoutMs: 150 })), /timed out/);
});

test('cancellation also terminates an actual descendant process', async t => {
  const directory = await mkdtemp(path.join(tmpdir(), 'dsh-ontology-tree-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const pidFile = path.join(directory, 'descendant.pid');
  const runner = createDshProcessRunner(await host(t));
  const controller = new AbortController();
  const child = 'require("node:fs").writeFileSync(process.argv[1],String(process.pid));setInterval(()=>{},1000)';
  const parent = `require('node:child_process').spawn(process.execPath,['-e',${JSON.stringify(child)},${JSON.stringify(pidFile)}],{stdio:'ignore'});setInterval(()=>{},1000)`;
  const running = runner(spec(parent, { signal: controller.signal }));
  // Attach rejection handling before asynchronous readiness polling.
  const settled = running.then(value => ({ value }), error => ({ error }));
  let pid;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { pid = Number(await readFile(pidFile, 'utf8')); break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; await delay(20); }
  }
  controller.abort(new Error('cancel entire tree'));
  const result = await settled;
  assert.ok(pid > 0, 'the real descendant must have started');
  assert.match(result.error?.message ?? '', /cancel entire tree/);
  assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' }, 'descendant must no longer exist after cancellation returns');
});

test('cancellation before dispatch does not start a process', async t => {
  const runner = createDshProcessRunner(await host(t));
  const controller = new AbortController();
  controller.abort(new Error('already cancelled'));
  await assert.rejects(runner(spec('process.exit(77)', { signal: controller.signal })), /already cancelled/);
});

test('local execution guard rejects an alternative provider instead of falling back', async t => {
  class AlternativeSubprocess extends LocalSubprocessRuntime {}
  const ctx = await host(t, AlternativeSubprocess);
  assert.throws(() => assertLocalExecution(ctx), /Remote or sandbox providers are unsupported/);
});
