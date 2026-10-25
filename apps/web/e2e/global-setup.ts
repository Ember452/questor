/**
 * Playwright 全局装配：起真 studio 宿主（--serve-no-auth，仅测试）+ vite preview，
 * 并把 /rt 代理到宿主端口；teardown 杀掉两个进程。
 */
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const REPO = resolve(WEB, "../..");
const PIDS = resolve(WEB, ".e2e-pids.json");

function python(): string {
  const venv = resolve(REPO, ".venv/Scripts/python.exe");
  if (process.platform === "win32" && existsSync(venv)) return venv;
  return process.env.QUESTOR_PYTHON ?? "python";
}

function readHandshake(child: import("node:child_process").ChildProcess): Promise<number> {
  return new Promise((resolvePort, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("studio host handshake timeout")), 30000);
    child.stdout?.on("data", (chunk: Buffer) => {
      buffer += chunk.toString("utf8");
      const index = buffer.indexOf("\n");
      if (index < 0) return;
      clearTimeout(timer);
      resolvePort(Number(JSON.parse(buffer.slice(0, index)).port));
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`studio host exited before handshake: ${code}`));
    });
  });
}

async function waitFor(url: string, timeoutMs = 30000): Promise<void> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      /* retry */
    }
    await new Promise((done) => setTimeout(done, 250));
  }
  throw new Error(`timeout waiting for ${url}`);
}

export default async function globalSetup(): Promise<void> {
  const engine = spawn(
    python(),
    ["-m", "questorharness", "--studio-host", "--serve-no-auth"],
    {
      // 临时 cwd：避免把开发机的真实会话快照带进截图矩阵。
      cwd: mkdtempSync(resolve(tmpdir(), "questor-e2e-")),
      env: { ...process.env, PYTHONPATH: resolve(REPO, "src"), PYTHONUTF8: "1" },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  const port = await readHandshake(engine);

  const preview = spawn(
    process.execPath,
    [
      resolve(WEB, "node_modules/vite/bin/vite.js"),
      "preview",
      "--host",
      "127.0.0.1",
      "--port",
      "4173",
      "--strictPort",
    ],
    {
      cwd: WEB,
      env: { ...process.env, QUESTOR_STUDIO_ORIGIN: `http://127.0.0.1:${port}` },
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    },
  );
  const log = existsSync(resolve(WEB, ".e2e-preview.log"))
    ? (await import("node:fs")).appendFileSync
    : (await import("node:fs")).writeFileSync;
  preview.stdout?.on("data", (chunk: Buffer) => log(resolve(WEB, ".e2e-preview.log"), chunk));
  preview.stderr?.on("data", (chunk: Buffer) => log(resolve(WEB, ".e2e-preview.log"), chunk));
  await waitFor("http://127.0.0.1:4173/");
  writeFileSync(PIDS, JSON.stringify({ engine: engine.pid, preview: preview.pid }), "utf8");
}
