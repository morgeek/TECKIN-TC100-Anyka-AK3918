/**
 * PostToolUse hook: auto-run `npm run build:web` when a file inside
 * frontend/src/ is edited or written, so www/ never drifts from source.
 *
 * Claude Code passes the tool event as JSON on stdin.
 */
import { createInterface } from 'readline';
import { execSync } from 'child_process';

let raw = '';
const rl = createInterface({ input: process.stdin, terminal: false });
for await (const line of rl) {
  raw += line + '\n';
}

try {
  const event = JSON.parse(raw.trim());
  const filePath = (event?.tool_input?.file_path || '').replace(/\\/g, '/');
  if (filePath.includes('frontend/src/')) {
    console.error('[hook] frontend/src/ changed — running npm run build:web');
    execSync('npm run build:web', { stdio: 'inherit', cwd: process.cwd() });
  }
} catch (_) {
  // Silently ignore: non-JSON stdin or missing fields are not errors.
}
