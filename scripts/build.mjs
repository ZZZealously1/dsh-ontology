import { build } from 'esbuild';
await build({ entryPoints: ['src/index.ts'], bundle: true, platform: 'node', format: 'esm',
  target: 'node24', outfile: 'lib/index.js', packages: 'external', sourcemap: false });
