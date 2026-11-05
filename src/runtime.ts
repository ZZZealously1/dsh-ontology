import * as fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// The built entry lives in lib/, as does this module's URL after bundling.
export const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const methodRoot = path.join(pluginRoot, 'Ontology');
export const engineRoot = path.join(methodRoot, 'Ontology-tools');
export interface RuntimeConfig {
  pythonExecutable?: string;
  javaExecutable?: string;
  workspaceRoots: string[];
  timeoutSeconds?: number;
}
export interface ProcessSpec {
  command: string; args: string[]; cwd: string; env?: Record<string, string>;
  signal: AbortSignal; timeoutMs: number; maxOutputBytes: number;
}
export interface ProcessResult { exitCode: number | null; stdout: string; stderr: string }
export type ProcessRunner = (spec: ProcessSpec) => Promise<ProcessResult>;
export interface CallContext { cwd: string; signal: AbortSignal }
export interface RunRequest {
  operation: string; package?: string; facts?: string[]; ontology?: string[];
  importsMap?: string; candidates?: string; graph?: string; query?: string;
  run?: string; output?: string; javaTimeout?: number;
}
export interface RunResult {
  status: string; exitCode: number; stage: string; semanticState: string | null;
  outputPath: string | null; artifacts: string[]; summary: string;
}
function within(parent: string, child: string): boolean {
  const relative = path.relative(parent, child);
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative));
}
async function canonical(value: string): Promise<string> {
  // Resolve through the nearest existing ancestor, including junctions/symlinks.
  let candidate = path.resolve(value);
  const missing: string[] = [];
  while (true) {
    try { return path.join(await fs.realpath(candidate), ...missing.reverse()); }
    catch (error: any) {
      if (error.code !== 'ENOENT') throw error;
      const parent = path.dirname(candidate);
      if (parent === candidate) throw error;
      missing.push(path.basename(candidate));
      candidate = parent;
    }
  }
}
function text(value: unknown, label: string): string {
  if (typeof value !== 'string' || !value.trim() || value.includes('\0')) throw new Error(`${label} must be nonempty text`);
  return value;
}
function checkSignal(signal: AbortSignal) { signal.throwIfAborted(); }

export function createOntologyRuntime(config: RuntimeConfig, processRunner: ProcessRunner) {
  const python = text(config.pythonExecutable ?? 'python', 'pythonExecutable');
  const java = text(config.javaExecutable ?? 'java', 'javaExecutable');
  const timeoutSeconds = config.timeoutSeconds ?? 900;
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 86400) throw new Error('timeoutSeconds must be an integer in 1..86400');
  if (!Array.isArray(config.workspaceRoots)) throw new Error('workspaceRoots must be an array');
  for (const root of config.workspaceRoots) if (!path.isAbsolute(text(root, 'workspaceRoot'))) throw new Error('workspaceRoots must be absolute');
  const roots = async () => Promise.all(config.workspaceRoots.map(root => fs.realpath(root)));
  const requireWorkspace = () => { if (!config.workspaceRoots.length) throw new Error('Configure at least one trusted workspaceRoot before running project operations'); };
  const installedPromise = fs.realpath(pluginRoot);

  async function resolveInput(value: string, context: CallContext, bundled = true) {
    checkSignal(context.signal);
    const candidate = await canonical(path.resolve(context.cwd, text(value, 'path')));
    const allowedRoots = await roots();
    const installed = await installedPromise;
    if (!allowedRoots.some(root => within(root, candidate)) && !(bundled && within(path.join(installed, 'Ontology'), candidate))) {
      throw new Error('Path is outside the configured workspace roots');
    }
    await fs.access(candidate);
    return candidate;
  }
  async function resolveOutput(value: string, context: CallContext) {
    checkSignal(context.signal);
    const candidate = await canonical(path.resolve(context.cwd, text(value, 'output path')));
    if (!(await roots()).some(root => within(root, candidate))) throw new Error('Output is outside the configured workspace roots');
    if (within(await installedPromise, candidate)) throw new Error('Writing into the plugin installation is forbidden');
    return candidate;
  }
  async function invoke(action: string, args: string[], context: CallContext): Promise<any> {
    checkSignal(context.signal);
    const result = await processRunner({command: python,
      args: ['-I', '-B', '-X', 'utf8', path.join(pluginRoot, 'bridge', 'ontology_bridge.py'), action, java, ...args],
      cwd: engineRoot, signal: context.signal, timeoutMs: timeoutSeconds * 1000,
      maxOutputBytes: 1024 * 1024, env: {PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8',
        PYTHONPATH:'', PYTHONHOME:'', JAVA_TOOL_OPTIONS:'', JDK_JAVA_OPTIONS:'', _JAVA_OPTIONS:''}});
    checkSignal(context.signal);
    let value;
    try { value = JSON.parse(result.stdout.trim()); }
    catch { throw new Error(`Ontology bridge did not return a valid response (exit ${result.exitCode}): ${result.stderr.slice(-4000)}`); }
    if (!value || typeof value !== 'object' || typeof value.status !== 'string') throw new Error('Ontology bridge returned an invalid response shape');
    if (result.exitCode !== 0 && value.exitCode !== result.exitCode) throw new Error(`Ontology bridge failed (exit ${result.exitCode}): ${result.stderr.slice(-4000)}`);
    return value;
  }
  return {
    async environment(context: CallContext) { return invoke('doctor', [], context); },
    async readMethod(request: {path?: string; offset?: number; limit?: number} = {}) {
      const relative = request.path ?? 'skills/ontology-builder/SKILL.md';
      if (path.isAbsolute(relative)) throw new Error('Method path must be relative to bundled Ontology');
      const target = await fs.realpath(path.resolve(methodRoot, text(relative, 'method path')));
      if (!within(await fs.realpath(methodRoot), target)) throw new Error('Method path escapes bundled Ontology');
      if (!['.md', '.txt', '.ttl', '.owl', '.swrl', '.rq', '.py'].includes(path.extname(target).toLowerCase())) throw new Error('Unsupported method resource format');
      const size = (await fs.stat(target)).size;
      if (size > 2 * 1024 * 1024) throw new Error('Method resource is too large; use project file tools');
      const offset = request.offset ?? 0, limit = request.limit ?? 16000;
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 64000) throw new Error('Invalid method slice; offset >= 0 and limit in 1..64000');
      const content = await fs.readFile(target, 'utf8');
      return {path: target, relativePath: path.relative(methodRoot, target).split(path.sep).join('/'),
        content: content.slice(offset, offset + limit), offset, nextOffset: offset + limit < content.length ? offset + limit : null,
        totalCharacters: content.length};
    },
    async run(request: RunRequest, context: CallContext): Promise<RunResult> {
      requireWorkspace();
      const operation = request.operation;
      if (!['inspect','validate','infer','test','query','replay','owl-dl','owl-infer','freeze'].includes(operation)) throw new Error('Unsupported ontology operation');
      const args = [operation];
      const input = async (flag: string, value: string | undefined) => args.push(flag, await resolveInput(text(value, flag), context));
      const optionalInput = async (flag: string, value?: string) => { if (value !== undefined) await input(flag, value); };
      const baseAllowed = new Set(['operation', 'output']);
      if (['inspect','validate','infer','test','freeze'].includes(operation)) {
        baseAllowed.add('package');
        const packagePath = await resolveInput(text(request.package, 'package'), context);
        if (!(await fs.stat(packagePath)).isDirectory()) throw new Error('package must be a directory');
        args.push('--package', packagePath);
        if (operation === 'freeze') {
          await resolveOutput(packagePath, context);
          if (request.output !== undefined) throw new Error('freeze writes a new package manifest and has no output argument');
        }
        if (['infer','validate'].includes(operation)) {
          baseAllowed.add('facts');
          if (request.facts !== undefined) {
            if (!Array.isArray(request.facts) || request.facts.length !== 1) throw new Error('Package inference accepts exactly one facts file');
            await input('--facts', request.facts[0]);
          }
        }
      } else if (operation === 'query') {
        baseAllowed.add('graph'); baseAllowed.add('query');
        await input('--graph', request.graph); await input('--query', request.query);
      } else if (operation === 'replay') {
        baseAllowed.add('run'); await input('--run', request.run);
      } else {
        for (const key of ['ontology','facts','importsMap','javaTimeout']) baseAllowed.add(key);
        if (!Array.isArray(request.ontology) || request.ontology.length === 0) throw new Error('OWL operation requires ontology files');
        for (const model of request.ontology) await input('--ontology', model);
        if (request.facts !== undefined && !Array.isArray(request.facts)) throw new Error('facts must be an array');
        for (const facts of request.facts ?? []) await input('--facts', facts);
        await optionalInput('--imports-map', request.importsMap);
        if (operation === 'owl-infer') { baseAllowed.add('candidates'); await optionalInput('--candidates', request.candidates); }
        args.push('--java', java);
        const seconds = request.javaTimeout ?? 60;
        if (!Number.isInteger(seconds) || seconds < 1 || seconds > timeoutSeconds) throw new Error('javaTimeout must be positive and no greater than the tool timeout');
        args.push('--timeout', String(seconds));
      }
      for (const key of Object.keys(request)) if (!baseAllowed.has(key) && (request as any)[key] !== undefined) throw new Error(`Unexpected argument for ${operation}: ${key}`);
      if (operation !== 'freeze') {
        const output = await resolveOutput(text(request.output, 'output'), context);
        try { await fs.lstat(output); throw new Error('Output directory already exists; choose a new run directory'); }
        catch (error: any) { if (error.code !== 'ENOENT') throw error; }
        args.push('--output', output);
      }
      return invoke('run', args, context);
    },
    async newProject(request: {destination: string; example: string}, context: CallContext) {
      requireWorkspace();
      if (!['tagging','family','projection','calculation','formula'].includes(request.example)) throw new Error('Choose a bundled synthetic example');
      const target = await resolveOutput(request.destination, context);
      try { await fs.lstat(target); throw new Error('Project destination already exists'); }
      catch (error: any) { if (error.code !== 'ENOENT') throw error; }
      checkSignal(context.signal);
      const source = path.join(engineRoot, 'examples', request.example);
      await fs.cp(source, target, {recursive:true, force:false, errorOnExist:true,
        filter: file => path.basename(file) !== 'manifest.sha256'});
      checkSignal(context.signal);
      return {status:'draft', outputPath:target, example:request.example,
        summary:'Editable synthetic example copied without its frozen manifest. Replace sample semantics using project sources, validate and freeze a new version.'};
    },
  };
}
