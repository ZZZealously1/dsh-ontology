import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import type { Context } from '@deepseek-ai/cordis';
import Schema from '@deepseek-ai/schemastery';
import { defineTool, type ToolRunContext } from '@deepseek-ai/dsh-tools';
import { BUNDLED_SKILL_RANK, type SkillCandidate } from '@deepseek-ai/dsh-skill';
import LocalFileSystem from '@deepseek-ai/dsh-fs-local';
import SandboxedFileSystem from '@deepseek-ai/dsh-fs-sandbox';
import LocalSubprocessRuntime from '@deepseek-ai/dsh-subprocess-local';
import { SandboxUnavailableError, classifyRunnerFailure, isRunnerSpawnFailure, matchesSignature,
  type ConfinedArgv, type SandboxExecutionPolicy } from '@deepseek-ai/dsh-sandbox';
import type {} from '@deepseek-ai/dsh-sandbox-policy';
import type {} from '@deepseek-ai/dsh-working-directory';
import { createOntologyRuntime, pluginRoot, methodRoot, type RuntimeConfig, type ProcessRunner, type CallContext } from './runtime.js';

export const name = 'dsh-ontology';
export const inject = ['tools', 'skills', 'fs', 'subprocess'];
export interface Config extends RuntimeConfig { defaultDirectory?: string }
export const Config: Schema<Config> = Schema.object({
  pythonExecutable: Schema.string().default('python').description('Trusted local Python executable containing Ontology dependencies.'),
  javaExecutable: Schema.string().default('java').description('Trusted local Java executable for HermiT.'),
  workspaceRoots: Schema.array(Schema.string()).default([]).description('Absolute existing directories authorized by the deployment owner for project input and output. Empty disables project operations.'),
  timeoutSeconds: Schema.number().min(1).max(86400).default(900).description('Execution budget in seconds; not a business threshold.'),
  defaultDirectory: Schema.string().description('Optional absolute default for non-agent calls. Agent calls always use their own session working directory.'),
});

/** rc.5 owns effective cwd in a service; rc.2 records it on the Session header. */
export async function resolveOntologyCallContext(ctx: Context, exec: ToolRunContext, defaultDirectory?: string): Promise<CallContext> {
  exec.signal.throwIfAborted();
  // get() is Cordis's documented optional-service lookup; the inject map itself
  // has no optional dependency syntax. Never fabricate a missing host service.
  const workingDirectory = ctx.get('workingDirectory');
  const cwd = exec.agent
    ? workingDirectory
      ? await workingDirectory.ensure(exec.agent, exec.signal)
      : exec.agent.session.header.cwd
    : defaultDirectory ?? workingDirectory?.defaultDirectory ?? process.cwd();
  exec.signal.throwIfAborted();
  if (typeof cwd !== 'string' || !cwd.trim() || !path.isAbsolute(cwd) || cwd.includes('\0')) {
    throw new Error(exec.agent
      ? 'The calling agent must have an absolute session working directory; refusing to use the host launch directory'
      : 'The deployment defaultDirectory must be an absolute path');
  }
  // This is the host's effective per-session policy, never a tool argument.
  const policyService = ctx.get('sandboxPolicy');
  const sandboxPolicy = policyService?.resolve({session:exec.agent?.session});
  if (policyService) validateSandboxPolicy(sandboxPolicy!);
  return { cwd, signal: exec.signal, ...(sandboxPolicy ? {sandboxPolicy} : {}) };
}

function validateSandboxPolicy(policy: SandboxExecutionPolicy): void {
  if (!policy || typeof policy !== 'object' || !['read-only','workspace-write','danger-full-access'].includes(policy.mode) ||
      typeof policy.workspaceRoot !== 'string' || !path.isAbsolute(policy.workspaceRoot) || policy.workspaceRoot.includes('\0')) {
    throw new Error('The host returned an invalid sandbox policy; no unconfined fallback is available');
  }
}

/** Trusted bundled reads require a known same-host filesystem execution world. */
export function assertLocalExecution(ctx: Context): void {
  // Cordis binds method-valued properties, including constructor, on service access.
  const bare = ctx.fs instanceof LocalFileSystem && Object.getPrototypeOf(ctx.fs) === LocalFileSystem.prototype;
  const sandboxed = ctx.fs instanceof SandboxedFileSystem && Object.getPrototypeOf(ctx.fs) === SandboxedFileSystem.prototype;
  if ((!bare && !sandboxed) ||
      !(ctx.subprocess instanceof LocalSubprocessRuntime) || Object.getPrototypeOf(ctx.subprocess) !== LocalSubprocessRuntime.prototype) {
    throw new Error('dsh-ontology requires dsh-fs-local or dsh-fs-sandbox with dsh-subprocess-local. Remote or unknown providers are unsupported; no local fallback is performed.');
  }
  if (sandboxed && !ctx.get('sandboxPolicy')) throw new Error('dsh-fs-sandbox requires its host sandboxPolicy service; no local fallback is performed');
}

/** Every project file is an atomic creation through the host filesystem. */
export function createDshProjectWriter(ctx: Context) {
  return async (file: string, content: string, context: CallContext): Promise<void> => {
    assertLocalExecution(ctx);
    const policyService = ctx.get('sandboxPolicy');
    const policy = context.sandboxPolicy ?? policyService?.resolve();
    if (policyService || policy) validateSandboxPolicy(policy!);
    // Bare fs does not enforce supplied policy; do not use it as a bypass when
    // a host has mounted sandboxPolicy alongside the bare filesystem.
    if (policy?.mode === 'read-only') throw new Error('DSH read-only policy denies project writes');
    const target = await ctx.fs.resolve(file,{cwd:context.cwd,signal:context.signal});
    if (policy?.mode === 'workspace-write' && !ctx.fs.contains(await ctx.fs.resolve(policy.workspaceRoot,{signal:context.signal}),target)) {
      throw new Error('Output is outside the calling session sandbox workspace');
    }
    await ctx.fs.writeText(target,content,{kind:'createIfAbsent'},context.signal,policy);
  };
}

/** Run through the host service, so cancellation terminates its managed process range. */
export function createDshProcessRunner(ctx: Context): ProcessRunner {
  return async spec => {
    assertLocalExecution(ctx);
    spec.signal.throwIfAborted();
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(new Error('Ontology execution timed out')), spec.timeoutMs);
    const signal = AbortSignal.any([spec.signal, timeout.signal]);
    try {
      const command = await ctx.subprocess.resolveExecutable(spec.command, spec.env, signal);
      signal.throwIfAborted();
      const policyService = ctx.get('sandboxPolicy');
      const policy = spec.sandboxPolicy ?? policyService?.resolve();
      if (policyService || policy) validateSandboxPolicy(policy!);
      let confined: ConfinedArgv | undefined;
      let argv = [command,...spec.args];
      if (policy && policy.mode !== 'danger-full-access') {
        const sandbox = ctx.get('sandbox');
        if (!sandbox) throw new SandboxUnavailableError(policy.mode,'The host has no process sandbox provider; unconfined fallback is forbidden');
        confined = await sandbox.confine(argv,{...policy,mode:policy.mode},signal);
        if (!confined.argv.length) throw new SandboxUnavailableError(policy.mode,'The sandbox returned an empty command');
        argv = confined.argv;
      }
      signal.throwIfAborted();
      const handle = ctx.subprocess.spawn({
        argv, cwd: spec.cwd, env: spec.env, signal, graceMs: 2000,
        stdio: { stdin: 'ignore', stdout: { maxBytes: spec.maxOutputBytes }, stderr: { maxBytes: spec.maxOutputBytes } },
      });
      try {
        const outcome = await handle.done;
        // A parent exit is insufficient while a Java or other descendant still runs.
        await handle.waitForExit(signal);
        signal.throwIfAborted();
        const stdout = handle.collected.stdout?.readFrom(0);
        const stderr = handle.collected.stderr?.readFrom(0);
        if (stdout?.lossy || stderr?.lossy) throw new Error('Ontology subprocess output exceeded the capture limit; the incomplete response was rejected');
        if (confined && policy && policy.mode !== 'danger-full-access') {
          const failure = classifyRunnerFailure(outcome.exitCode,stderr?.text ?? '',confined.runnerFailureRules);
          if (failure) throw new SandboxUnavailableError(policy.mode,failure.detail);
          if (matchesSignature(outcome.exitCode,stderr?.text ?? '',confined.denialSignatures)) {
            throw new Error(`DSH sandbox denied a file effect under ${policy.mode}; the operation was not rerun without confinement`);
          }
        }
        return { exitCode: outcome.exitCode, stdout: stdout?.text ?? '', stderr: stderr?.text ?? '',
          ...(policy ? {sandbox:{mode:policy.mode,...(confined ? {enforcement:confined.enforcement} : {})}} : {}) };
      } catch (error) {
        handle.terminate();
        const gone = await handle.waitForExit(AbortSignal.timeout(10000));
        if (!gone) throw new Error('Ontology process cancellation could not confirm termination of the managed process range', { cause: error });
        if (confined && policy && policy.mode !== 'danger-full-access' && isRunnerSpawnFailure(error,confined.argv[0],spec.cwd)) {
          throw new SandboxUnavailableError(policy.mode,String(error));
        }
        throw error;
      }
    } finally {
      clearTimeout(timer);
    }
  };
}

function registerSkills(ctx: Context): void {
  ctx.skills.registerProvider(control => {
    const catalog = async (signal?: AbortSignal) => {
      const combined = signal ? AbortSignal.any([signal, control.signal]) : control.signal;
      combined.throwIfAborted();
      const directories = (await readdir(path.join(methodRoot, 'skills'), { withFileTypes: true }))
        .filter(entry => entry.isDirectory()).map(entry => path.join(methodRoot, 'skills', entry.name));
      directories.unshift(path.join(pluginRoot, 'skills', 'ontology'));
      return Promise.all(directories.map(async directory => {
        const file = path.join(directory, 'SKILL.md');
        const source = await readFile(file, { encoding: 'utf8', signal: combined });
        // Packaged skills deliberately use two plain, single-line routing fields.
        const header = /^---\r?\nname: ([^\r\n]+)\r?\ndescription: ([^\r\n]+)\r?\n---\r?\n/.exec(source);
        if (!header || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(header[1])) throw new Error(`Unsupported packaged skill metadata: ${file}`);
        const candidate: SkillCandidate = {
          name: header[1], description: header[2], path: file, rank: BUNDLED_SKILL_RANK,
          provider: name, source: 'bundled', invocation: { modelInvocable: true, userInvocable: true },
          resourceBase: { kind: 'directory', path: directory }, locator: file,
        };
        return { candidate, content: source.slice(header[0].length) };
      }));
    };
    return {
      name,
      async list(options) { return (await catalog(options.signal)).map(item => item.candidate); },
      async get(candidate, options) {
        const found = (await catalog(options.signal)).find(item => item.candidate.locator === candidate.locator);
        return found ? { ...found.candidate, content: found.content } : undefined;
      },
    };
  });
}

const runParameters = {
  operation: { type: 'string', enum: ['inspect', 'validate', 'infer', 'test', 'query', 'replay', 'owl-dl', 'owl-infer', 'freeze'], required: true },
  package: { type: 'string', description: 'Flat runtime package directory for inspect/validate/infer/test/freeze.' },
  facts: { type: 'array', items: { type: 'string' }, description: 'Fact files; package inference/validation accepts exactly one override.' },
  ontology: { type: 'array', items: { type: 'string' }, description: 'Explicit model files for owl-dl/owl-infer.' },
  importsMap: { type: 'string', description: 'Local Turtle import map for OWL operations.' },
  candidates: { type: 'string', description: 'Frozen candidate Turtle file for owl-infer.' },
  graph: { type: 'string', description: 'Graph file for query.' },
  query: { type: 'string', description: 'Local SPARQL query file; not inline shell or code.' },
  run: { type: 'string', description: 'Saved execution directory for replay.' },
  output: { type: 'string', description: 'New output directory inside trusted workspace roots; required except freeze.' },
  javaTimeout: { type: 'integer', description: 'Per-Java-call time budget for owl-dl/owl-infer, default 60 seconds.' },
} as const;

const runOutput = {
  type: 'object', additionalProperties: false,
  properties: {
    status: { type: 'string', required: true }, exitCode: { type: 'integer', required: true },
    stage: { type: 'string', required: true },
    semanticState: { oneOf: [{ type: 'string' }, { type: 'null' }], required: true },
    outputPath: { oneOf: [{ type: 'string' }, { type: 'null' }], required: true },
    artifacts: { type: 'array', items: { type: 'string' }, required: true },
    summary: { type: 'string', required: true },
  },
} as const;

export function apply(ctx: Context, config: Config): void {
  assertLocalExecution(ctx);
  if (config.defaultDirectory !== undefined && (!path.isAbsolute(config.defaultDirectory) || config.defaultDirectory.includes('\0'))) {
    throw new Error('defaultDirectory must be an absolute path');
  }
  const runtime = createOntologyRuntime(config, createDshProcessRunner(ctx), createDshProjectWriter(ctx));
  const context = async (exec: ToolRunContext) => {
    assertLocalExecution(ctx);
    return resolveOntologyCallContext(ctx, exec, config.defaultDirectory);
  };
  registerSkills(ctx);
  ctx.tools.register(defineTool({
    name: 'ontology_environment', description: 'Check the bundled Ontology engine, local Python dependencies, Java and actual reasoning capabilities. Does not install dependencies.',
    parameters: {}, output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
    async execute(_args, exec) { return runtime.environment(await context(exec)); },
  }));
  ctx.tools.register(defineTool({
    name: 'ontology_read_method', description: 'Read a bounded text resource from the bundled Ontology method library. Paths are relative to Ontology, never arbitrary system paths.',
    parameters: { path: { type: 'string' }, offset: { type: 'integer' }, limit: { type: 'integer' } },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
    isConcurrencySafe: () => true,
    async execute(args, exec) { exec.signal.throwIfAborted(); return runtime.readMethod(args); },
  }));
  ctx.tools.register(defineTool({
    name: 'ontology_run', description: 'Run the bundled Ontology CLI through the host subprocess service. Preserves configured finite-rule, OWL DL, projection, calculation and formula backends. Inspect status and semanticState; execution completion alone does not mean acceptance passed. No external connections.',
    parameters: runParameters,
    output: { schema: runOutput, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
    async execute(args, exec) { return runtime.run(args, await context(exec)); },
  }));
  ctx.tools.register(defineTool({
    name: 'ontology_new_project', description: 'Copy an editable synthetic starter into a new project ontology directory. This is example scaffolding, not a business model inferred from the user’s sources. Validate and freeze after adapting it.',
    parameters: {
      destination: { type: 'string', required: true },
      example: { type: 'string', enum: ['tagging', 'family', 'projection', 'calculation', 'formula'], required: true },
    },
    output: { schema: { type: 'json' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value, null, 2) }] },
    async execute(args, exec) { return runtime.newProject(args, await context(exec)); },
  }));
}
