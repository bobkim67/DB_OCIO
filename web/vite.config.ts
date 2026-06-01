import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

// `.runtime_ports.json` is written by scripts/pick_free_port.py
// (launch_fastapi.bat / launch_vite.bat). Fall back to defaults when missing.
function readRuntimePorts(): { api: number; web: number } {
  const defaults = { api: 8000, web: 5173 };
  const path = resolve(__dirname, "..", ".runtime_ports.json");
  if (!existsSync(path)) return defaults;
  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as Record<string, unknown>;
    const toInt = (v: unknown, fb: number) => {
      const n = typeof v === "number" ? v : Number(v);
      return Number.isFinite(n) && n > 0 ? Math.floor(n) : fb;
    };
    return {
      api: toInt(parsed.api, defaults.api),
      web: toInt(parsed.web, defaults.web),
    };
  } catch {
    return defaults;
  }
}

const { api: API_PORT, web: WEB_PORT } = readRuntimePorts();

export default defineConfig({
  plugins: [react()],
  server: {
    port: WEB_PORT,
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${API_PORT}`,
        changeOrigin: true,
      },
    },
  },
});
