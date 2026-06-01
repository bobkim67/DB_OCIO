// openapi.d.ts 생성 — FastAPI 포트를 ../.runtime_ports.json 에서 읽는다.
// launcher 가 동적 포트로 띄우므로 8000 하드코딩 대신 실제 포트를 사용.
// fallback 8000. CLI 인자로 포트 강제 지정 가능: node scripts/gen-openapi.mjs 8003
import { execSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(__dirname, "..");

function resolvePort() {
  const argPort = Number(process.argv[2]);
  if (Number.isFinite(argPort) && argPort > 0) return argPort;
  const portsPath = resolve(webRoot, "..", ".runtime_ports.json");
  if (existsSync(portsPath)) {
    try {
      const j = JSON.parse(readFileSync(portsPath, "utf-8"));
      const p = Number(j.api);
      if (Number.isFinite(p) && p > 0) return p;
    } catch {
      // fall through to default
    }
  }
  return 8000;
}

const port = resolvePort();
const url = `http://127.0.0.1:${port}/openapi.json`;
console.log(`[openapi:gen] ${url}`);
execSync(
  `openapi-typescript ${url} -o src/api/generated/openapi.d.ts`,
  { stdio: "inherit", cwd: webRoot },
);
