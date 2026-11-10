// src/index.ts
import { readFile as readFile2, readdir } from "node:fs/promises";
import path2 from "node:path";
import Schema from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";
import { BUNDLED_SKILL_RANK } from "@deepseek-ai/dsh-skill";
import LocalFileSystem from "@deepseek-ai/dsh-fs-local";
import LocalSubprocessRuntime from "@deepseek-ai/dsh-subprocess-local";

// src/runtime.ts
import * as fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
var pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
var methodRoot = path.join(pluginRoot, "Ontology");
var engineRoot = path.join(methodRoot, "Ontology-tools");
function within(parent, child) {
  const relative = path.relative(parent, child);
  return relative === "" || !relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative);
}
async function canonical(value) {
  let candidate = path.resolve(value);
  const missing = [];
  while (true) {
    try {
      return path.join(await fs.realpath(candidate), ...missing.reverse());
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
      const parent = path.dirname(candidate);
      if (parent === candidate) throw error;
      missing.push(path.basename(candidate));
      candidate = parent;
    }
  }
}
function text(value, label) {
  if (typeof value !== "string" || !value.trim() || value.includes("\0")) throw new Error(`${label} must be nonempty text`);
  return value;
}
function checkSignal(signal) {
  signal.throwIfAborted();
}
function createOntologyRuntime(config, processRunner) {
  const python = text(config.pythonExecutable ?? "python", "pythonExecutable");
  const java = text(config.javaExecutable ?? "java", "javaExecutable");
  const timeoutSeconds = config.timeoutSeconds ?? 900;
  if (!Number.isInteger(timeoutSeconds) || timeoutSeconds < 1 || timeoutSeconds > 86400) throw new Error("timeoutSeconds must be an integer in 1..86400");
  if (!Array.isArray(config.workspaceRoots)) throw new Error("workspaceRoots must be an array");
  for (const root of config.workspaceRoots) if (!path.isAbsolute(text(root, "workspaceRoot"))) throw new Error("workspaceRoots must be absolute");
  const roots = async () => Promise.all(config.workspaceRoots.map((root) => fs.realpath(root)));
  const requireWorkspace = () => {
    if (!config.workspaceRoots.length) throw new Error("Configure at least one trusted workspaceRoot before running project operations");
  };
  const installedPromise = fs.realpath(pluginRoot);
  async function resolveInput(value, context, bundled = true) {
    checkSignal(context.signal);
    const candidate = await canonical(path.resolve(context.cwd, text(value, "path")));
    const allowedRoots = await roots();
    const installed = await installedPromise;
    if (!allowedRoots.some((root) => within(root, candidate)) && !(bundled && within(path.join(installed, "Ontology"), candidate))) {
      throw new Error("Path is outside the configured workspace roots");
    }
    await fs.access(candidate);
    return candidate;
  }
  async function resolveOutput(value, context) {
    checkSignal(context.signal);
    const candidate = await canonical(path.resolve(context.cwd, text(value, "output path")));
    if (!(await roots()).some((root) => within(root, candidate))) throw new Error("Output is outside the configured workspace roots");
    if (within(await installedPromise, candidate)) throw new Error("Writing into the plugin installation is forbidden");
    return candidate;
  }
  async function invoke(action, args, context) {
    checkSignal(context.signal);
    const result = await processRunner({
      command: python,
      args: ["-I", "-B", "-X", "utf8", path.join(pluginRoot, "bridge", "ontology_bridge.py"), action, java, ...args],
      cwd: engineRoot,
      signal: context.signal,
      timeoutMs: timeoutSeconds * 1e3,
      maxOutputBytes: 1024 * 1024,
      env: {
        PYTHONDONTWRITEBYTECODE: "1",
        PYTHONIOENCODING: "utf-8",
        PYTHONPATH: "",
        PYTHONHOME: "",
        JAVA_TOOL_OPTIONS: "",
        JDK_JAVA_OPTIONS: "",
        _JAVA_OPTIONS: ""
      }
    });
    checkSignal(context.signal);
    let value;
    try {
      value = JSON.parse(result.stdout.trim());
    } catch {
      throw new Error(`Ontology bridge did not return a valid response (exit ${result.exitCode}): ${result.stderr.slice(-4e3)}`);
    }
    if (!value || typeof value !== "object" || typeof value.status !== "string") throw new Error("Ontology bridge returned an invalid response shape");
    if (result.exitCode !== 0 && value.exitCode !== result.exitCode) throw new Error(`Ontology bridge failed (exit ${result.exitCode}): ${result.stderr.slice(-4e3)}`);
    return value;
  }
  return {
    async environment(context) {
      return invoke("doctor", [], context);
    },
    async readMethod(request = {}) {
      const relative = request.path ?? "skills/ontology-builder/SKILL.md";
      if (path.isAbsolute(relative)) throw new Error("Method path must be relative to bundled Ontology");
      const target = await fs.realpath(path.resolve(methodRoot, text(relative, "method path")));
      if (!within(await fs.realpath(methodRoot), target)) throw new Error("Method path escapes bundled Ontology");
      if (![".md", ".txt", ".ttl", ".owl", ".swrl", ".rq", ".py"].includes(path.extname(target).toLowerCase())) throw new Error("Unsupported method resource format");
      const size = (await fs.stat(target)).size;
      if (size > 2 * 1024 * 1024) throw new Error("Method resource is too large; use project file tools");
      const offset = request.offset ?? 0, limit = request.limit ?? 16e3;
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(limit) || limit < 1 || limit > 64e3) throw new Error("Invalid method slice; offset >= 0 and limit in 1..64000");
      const content = await fs.readFile(target, "utf8");
      return {
        path: target,
        relativePath: path.relative(methodRoot, target).split(path.sep).join("/"),
        content: content.slice(offset, offset + limit),
        offset,
        nextOffset: offset + limit < content.length ? offset + limit : null,
        totalCharacters: content.length
      };
    },
    async run(request, context) {
      requireWorkspace();
      const operation = request.operation;
      if (!["inspect", "validate", "infer", "test", "query", "replay", "owl-dl", "owl-infer", "freeze"].includes(operation)) throw new Error("Unsupported ontology operation");
      const args = [operation];
      const input = async (flag, value) => args.push(flag, await resolveInput(text(value, flag), context));
      const optionalInput = async (flag, value) => {
        if (value !== void 0) await input(flag, value);
      };
      const baseAllowed = /* @__PURE__ */ new Set(["operation", "output"]);
      if (["inspect", "validate", "infer", "test", "freeze"].includes(operation)) {
        baseAllowed.add("package");
        const packagePath = await resolveInput(text(request.package, "package"), context);
        if (!(await fs.stat(packagePath)).isDirectory()) throw new Error("package must be a directory");
        args.push("--package", packagePath);
        if (operation === "freeze") {
          await resolveOutput(packagePath, context);
          if (request.output !== void 0) throw new Error("freeze writes a new package manifest and has no output argument");
        }
        if (["infer", "validate"].includes(operation)) {
          baseAllowed.add("facts");
          if (request.facts !== void 0) {
            if (!Array.isArray(request.facts) || request.facts.length !== 1) throw new Error("Package inference accepts exactly one facts file");
            await input("--facts", request.facts[0]);
          }
        }
      } else if (operation === "query") {
        baseAllowed.add("graph");
        baseAllowed.add("query");
        await input("--graph", request.graph);
        await input("--query", request.query);
      } else if (operation === "replay") {
        baseAllowed.add("run");
        await input("--run", request.run);
      } else {
        for (const key of ["ontology", "facts", "importsMap", "javaTimeout"]) baseAllowed.add(key);
        if (!Array.isArray(request.ontology) || request.ontology.length === 0) throw new Error("OWL operation requires ontology files");
        for (const model of request.ontology) await input("--ontology", model);
        if (request.facts !== void 0 && !Array.isArray(request.facts)) throw new Error("facts must be an array");
        for (const facts of request.facts ?? []) await input("--facts", facts);
        await optionalInput("--imports-map", request.importsMap);
        if (operation === "owl-infer") {
          baseAllowed.add("candidates");
          await optionalInput("--candidates", request.candidates);
        }
        args.push("--java", java);
        const seconds = request.javaTimeout ?? 60;
        if (!Number.isInteger(seconds) || seconds < 1 || seconds > timeoutSeconds) throw new Error("javaTimeout must be positive and no greater than the tool timeout");
        args.push("--timeout", String(seconds));
      }
      for (const key of Object.keys(request)) if (!baseAllowed.has(key) && request[key] !== void 0) throw new Error(`Unexpected argument for ${operation}: ${key}`);
      if (operation !== "freeze") {
        const output = await resolveOutput(text(request.output, "output"), context);
        try {
          await fs.lstat(output);
          throw new Error("Output directory already exists; choose a new run directory");
        } catch (error) {
          if (error.code !== "ENOENT") throw error;
        }
        args.push("--output", output);
      }
      return invoke("run", args, context);
    },
    async newProject(request, context) {
      requireWorkspace();
      if (!["tagging", "family", "projection", "calculation", "formula"].includes(request.example)) throw new Error("Choose a bundled synthetic example");
      const target = await resolveOutput(request.destination, context);
      try {
        await fs.lstat(target);
        throw new Error("Project destination already exists");
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      checkSignal(context.signal);
      const source = path.join(engineRoot, "examples", request.example);
      await fs.cp(source, target, {
        recursive: true,
        force: false,
        errorOnExist: true,
        filter: (file) => path.basename(file) !== "manifest.sha256"
      });
      checkSignal(context.signal);
      return {
        status: "draft",
        outputPath: target,
        example: request.example,
        summary: "Editable synthetic example copied without its frozen manifest. Replace sample semantics using project sources, validate and freeze a new version."
      };
    }
  };
}

// src/index.ts
var name = "dsh-ontology";
var inject = ["tools", "skills", "fs", "subprocess"];
var Config = Schema.object({
  pythonExecutable: Schema.string().default("python").description("Trusted local Python executable containing Ontology dependencies."),
  javaExecutable: Schema.string().default("java").description("Trusted local Java executable for HermiT."),
  workspaceRoots: Schema.array(Schema.string()).default([]).description("Absolute existing directories authorized by the deployment owner for project input and output. Empty disables project operations."),
  timeoutSeconds: Schema.number().min(1).max(86400).default(900).description("Execution budget in seconds; not a business threshold."),
  defaultDirectory: Schema.string().description("Optional absolute default for non-agent calls. Agent calls always use their own session working directory.")
});
async function resolveOntologyCallContext(ctx, exec, defaultDirectory) {
  exec.signal.throwIfAborted();
  const workingDirectory = ctx.get("workingDirectory");
  const cwd = exec.agent ? workingDirectory ? await workingDirectory.ensure(exec.agent, exec.signal) : exec.agent.session.header.cwd : defaultDirectory ?? workingDirectory?.defaultDirectory ?? process.cwd();
  exec.signal.throwIfAborted();
  if (typeof cwd !== "string" || !cwd.trim() || !path2.isAbsolute(cwd) || cwd.includes("\0")) {
    throw new Error(exec.agent ? "The calling agent must have an absolute session working directory; refusing to use the host launch directory" : "The deployment defaultDirectory must be an absolute path");
  }
  return { cwd, signal: exec.signal };
}
function assertLocalExecution(ctx) {
  if (!(ctx.fs instanceof LocalFileSystem) || Object.getPrototypeOf(ctx.fs) !== LocalFileSystem.prototype || !(ctx.subprocess instanceof LocalSubprocessRuntime) || Object.getPrototypeOf(ctx.subprocess) !== LocalSubprocessRuntime.prototype) {
    throw new Error("dsh-ontology requires the bare dsh-fs-local and dsh-subprocess-local providers. Remote or sandbox providers are unsupported; no local fallback is performed.");
  }
}
function createDshProcessRunner(ctx) {
  return async (spec) => {
    assertLocalExecution(ctx);
    spec.signal.throwIfAborted();
    const timeout = new AbortController();
    const timer = setTimeout(() => timeout.abort(new Error("Ontology execution timed out")), spec.timeoutMs);
    const signal = AbortSignal.any([spec.signal, timeout.signal]);
    try {
      const command = await ctx.subprocess.resolveExecutable(spec.command, spec.env, signal);
      signal.throwIfAborted();
      const handle = ctx.subprocess.spawn({
        argv: [command, ...spec.args],
        cwd: spec.cwd,
        env: spec.env,
        signal,
        graceMs: 2e3,
        stdio: { stdin: "ignore", stdout: { maxBytes: spec.maxOutputBytes }, stderr: { maxBytes: spec.maxOutputBytes } }
      });
      try {
        const outcome = await handle.done;
        await handle.waitForExit(signal);
        signal.throwIfAborted();
        const stdout = handle.collected.stdout?.readFrom(0);
        const stderr = handle.collected.stderr?.readFrom(0);
        if (stdout?.lossy || stderr?.lossy) throw new Error("Ontology subprocess output exceeded the capture limit; the incomplete response was rejected");
        return { exitCode: outcome.exitCode, stdout: stdout?.text ?? "", stderr: stderr?.text ?? "" };
      } catch (error) {
        handle.terminate();
        const gone = await handle.waitForExit(AbortSignal.timeout(1e4));
        if (!gone) throw new Error("Ontology process cancellation could not confirm termination of the managed process range", { cause: error });
        throw error;
      }
    } finally {
      clearTimeout(timer);
    }
  };
}
function registerSkills(ctx) {
  ctx.skills.registerProvider((control) => {
    const catalog = async (signal) => {
      const combined = signal ? AbortSignal.any([signal, control.signal]) : control.signal;
      combined.throwIfAborted();
      const directories = (await readdir(path2.join(methodRoot, "skills"), { withFileTypes: true })).filter((entry) => entry.isDirectory()).map((entry) => path2.join(methodRoot, "skills", entry.name));
      directories.unshift(path2.join(pluginRoot, "skills", "ontology"));
      return Promise.all(directories.map(async (directory) => {
        const file = path2.join(directory, "SKILL.md");
        const source = await readFile2(file, { encoding: "utf8", signal: combined });
        const header = /^---\r?\nname: ([^\r\n]+)\r?\ndescription: ([^\r\n]+)\r?\n---\r?\n/.exec(source);
        if (!header || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(header[1])) throw new Error(`Unsupported packaged skill metadata: ${file}`);
        const candidate = {
          name: header[1],
          description: header[2],
          path: file,
          rank: BUNDLED_SKILL_RANK,
          provider: name,
          source: "bundled",
          invocation: { modelInvocable: true, userInvocable: true },
          resourceBase: { kind: "directory", path: directory },
          locator: file
        };
        return { candidate, content: source.slice(header[0].length) };
      }));
    };
    return {
      name,
      async list(options) {
        return (await catalog(options.signal)).map((item) => item.candidate);
      },
      async get(candidate, options) {
        const found = (await catalog(options.signal)).find((item) => item.candidate.locator === candidate.locator);
        return found ? { ...found.candidate, content: found.content } : void 0;
      }
    };
  });
}
var runParameters = {
  operation: { type: "string", enum: ["inspect", "validate", "infer", "test", "query", "replay", "owl-dl", "owl-infer", "freeze"], required: true },
  package: { type: "string", description: "Flat runtime package directory for inspect/validate/infer/test/freeze." },
  facts: { type: "array", items: { type: "string" }, description: "Fact files; package inference/validation accepts exactly one override." },
  ontology: { type: "array", items: { type: "string" }, description: "Explicit model files for owl-dl/owl-infer." },
  importsMap: { type: "string", description: "Local Turtle import map for OWL operations." },
  candidates: { type: "string", description: "Frozen candidate Turtle file for owl-infer." },
  graph: { type: "string", description: "Graph file for query." },
  query: { type: "string", description: "Local SPARQL query file; not inline shell or code." },
  run: { type: "string", description: "Saved execution directory for replay." },
  output: { type: "string", description: "New output directory inside trusted workspace roots; required except freeze." },
  javaTimeout: { type: "integer", description: "Per-Java-call time budget for owl-dl/owl-infer, default 60 seconds." }
};
var runOutput = {
  type: "object",
  additionalProperties: false,
  properties: {
    status: { type: "string", required: true },
    exitCode: { type: "integer", required: true },
    stage: { type: "string", required: true },
    semanticState: { oneOf: [{ type: "string" }, { type: "null" }], required: true },
    outputPath: { oneOf: [{ type: "string" }, { type: "null" }], required: true },
    artifacts: { type: "array", items: { type: "string" }, required: true },
    summary: { type: "string", required: true }
  }
};
function apply(ctx, config) {
  assertLocalExecution(ctx);
  if (config.defaultDirectory !== void 0 && (!path2.isAbsolute(config.defaultDirectory) || config.defaultDirectory.includes("\0"))) {
    throw new Error("defaultDirectory must be an absolute path");
  }
  const runtime = createOntologyRuntime(config, createDshProcessRunner(ctx));
  const context = async (exec) => {
    assertLocalExecution(ctx);
    return resolveOntologyCallContext(ctx, exec, config.defaultDirectory);
  };
  registerSkills(ctx);
  ctx.tools.register(defineTool({
    name: "ontology_environment",
    description: "Check the bundled Ontology engine, local Python dependencies, Java and actual reasoning capabilities. Does not install dependencies.",
    parameters: {},
    output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }] },
    async execute(_args, exec) {
      return runtime.environment(await context(exec));
    }
  }));
  ctx.tools.register(defineTool({
    name: "ontology_read_method",
    description: "Read a bounded text resource from the bundled Ontology method library. Paths are relative to Ontology, never arbitrary system paths.",
    parameters: { path: { type: "string" }, offset: { type: "integer" }, limit: { type: "integer" } },
    output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }] },
    isConcurrencySafe: () => true,
    async execute(args, exec) {
      exec.signal.throwIfAborted();
      return runtime.readMethod(args);
    }
  }));
  ctx.tools.register(defineTool({
    name: "ontology_run",
    description: "Run the bundled Ontology CLI through the host subprocess service. Preserves configured finite-rule, OWL DL, projection, calculation and formula backends. Inspect status and semanticState; execution completion alone does not mean acceptance passed. No external connections.",
    parameters: runParameters,
    output: { schema: runOutput, render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }] },
    async execute(args, exec) {
      return runtime.run(args, await context(exec));
    }
  }));
  ctx.tools.register(defineTool({
    name: "ontology_new_project",
    description: "Copy an editable synthetic starter into a new project ontology directory. This is example scaffolding, not a business model inferred from the user\u2019s sources. Validate and freeze after adapting it.",
    parameters: {
      destination: { type: "string", required: true },
      example: { type: "string", enum: ["tagging", "family", "projection", "calculation", "formula"], required: true }
    },
    output: { schema: { type: "json" }, render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }] },
    async execute(args, exec) {
      return runtime.newProject(args, await context(exec));
    }
  }));
}
export {
  Config,
  apply,
  assertLocalExecution,
  createDshProcessRunner,
  inject,
  name,
  resolveOntologyCallContext
};
