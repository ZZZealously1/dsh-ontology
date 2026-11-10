import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { Context } from '@deepseek-ai/cordis';
import { inject, resolveOntologyCallContext } from '../lib/index.js';

const sessionCwd = path.resolve('session-project');
const currentCwd = path.resolve('session-current-directory');
const deploymentCwd = path.resolve('deployment-default');
const call = (agent) => ({ agent, signal:new AbortController().signal });

test('legacy host needs only the four real required services', () => {
  assert.deepEqual(inject, ['tools', 'skills', 'fs', 'subprocess']);
});
test('rc.2 agent calls use their session cwd instead of deployment or launch cwd', async () => {
  const ctx = new Context();
  const exec = call({ session:{ header:{ cwd:sessionCwd } } });
  assert.equal((await resolveOntologyCallContext(ctx, exec, deploymentCwd)).cwd, sessionCwd);
  await ctx.fiber.dispose();
});
test('missing, relative or invalid legacy agent cwd is rejected rather than falling back', async () => {
  const ctx = new Context();
  for (const cwd of [undefined, '', 'relative-project', 42, `${sessionCwd}\0`]) {
    await assert.rejects(resolveOntologyCallContext(ctx, call({ session:{ header:{ cwd } } }), deploymentCwd), /absolute session/);
  }
  await ctx.fiber.dispose();
});
test('non-agent calls use the explicit deployment default or the host launch cwd', async () => {
  const ctx = new Context();
  assert.equal((await resolveOntologyCallContext(ctx, call(), deploymentCwd)).cwd, deploymentCwd);
  assert.equal((await resolveOntologyCallContext(ctx, call())).cwd, process.cwd());
  await assert.rejects(resolveOntologyCallContext(ctx, call(), 'relative-default'), /absolute path/);
  await ctx.fiber.dispose();
});
test('rc.5 service effective cwd and cancellation contract take precedence over immutable header', async () => {
  const ctx = new Context();
  const agent = {session:{header:{cwd:sessionCwd}}};
  const exec = call(agent);
  let calls = 0;
  ctx.provide('workingDirectory', {
    defaultDirectory:deploymentCwd,
    async ensure(receivedAgent, receivedSignal) {
      calls++;
      assert.equal(receivedAgent,agent); assert.equal(receivedSignal,exec.signal);
      return currentCwd;
    },
  });
  assert.equal((await resolveOntologyCallContext(ctx,exec)).cwd,currentCwd);
  assert.equal(calls,1);
  assert.equal((await resolveOntologyCallContext(ctx,call())).cwd,deploymentCwd);
  await ctx.fiber.dispose();
});
test('a failing or invalid rc.5 service cannot silently fall back to header cwd', async () => {
  const ctx = new Context();
  const release = ctx.provide('workingDirectory', { async ensure(){throw new Error('directory unavailable');} });
  const exec = call({session:{header:{cwd:sessionCwd}}});
  await assert.rejects(resolveOntologyCallContext(ctx,exec),/directory unavailable/);
  await release();
  ctx.provide('workingDirectory', { async ensure(){return 'relative';} });
  await assert.rejects(resolveOntologyCallContext(ctx,exec),/absolute session/);
  await ctx.fiber.dispose();
});
test('pre-cancelled and cancelled-during-resolution calls fail before any ontology operation', async () => {
  const ctx = new Context();
  await assert.rejects(resolveOntologyCallContext(ctx,{signal:AbortSignal.abort(new Error('cancelled'))}),/cancelled/);
  const controller = new AbortController();
  ctx.provide('workingDirectory', {async ensure(){controller.abort(new Error('cancelled during resolution'));return currentCwd;}});
  await assert.rejects(resolveOntologyCallContext(ctx,{agent:{session:{header:{cwd:sessionCwd}}},signal:controller.signal}),/cancelled during resolution/);
  await ctx.fiber.dispose();
});
