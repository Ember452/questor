/**
 * 长期运行冒烟：启动打包引擎 → 每 5s 打一次 /profile → 采样 RSS。
 * 默认 60s（CI/本地冒烟）；8h 基线用 `SOAK_SECONDS=28800 node scripts/soak.mjs`。
 */
import { spawn, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");
const EXE = process.env.QUESTOR_ENGINE ?? resolve(REPO, "apps/desktop/dist/engine/questor-engine.exe");
const SECONDS = Number(process.env.SOAK_SECONDS ?? 60);

function rssMb(pid) {
  if (process.platform === "win32") {
    const out = spawnSync("tasklist", ["/FI", `PID eq ${pid}`, "/FO", "CSV", "/NH"], { encoding: "utf8" }).stdout;
    const match = out.match(/"([^"]+)","([^"]+)","([^"]+)","([^"]+)","([\d,]+) K"/);
    return match ? Number(match[5].replace(/,/g, "")) / 1024 : null;
  }
  const out = spawnSync("ps", ["-o", "rss=", "-p", String(pid)], { encoding: "utf8" }).stdout.trim();
  return out ? Number(out) / 1024 : null;
}

const child = spawn(EXE, ["--studio-host", "--serve-no-auth"], {
  cwd: dirname(EXE),
  stdio: ["pipe", "pipe", "pipe"],
});
const handshake = await new Promise((resolveLine, reject) => {
  let buffer = "";
  const timer = setTimeout(() => reject(new Error("handshake timeout")), 30000);
  child.stdout.on("data", (chunk) => {
    buffer += chunk.toString("utf8");
    const index = buffer.indexOf("\n");
    if (index < 0) return;
    clearTimeout(timer);
    resolveLine(JSON.parse(buffer.slice(0, index)));
  });
});
const origin = `http://127.0.0.1:${handshake.port}`;
const samples = [];
const deadline = Date.now() + SECONDS * 1000;
while (Date.now() < deadline) {
  const response = await fetch(`${origin}/rt/r1/profile`);
  const rss = rssMb(child.pid);
  samples.push(rss);
  console.log(`t=${Math.round((Date.now() - (deadline - SECONDS * 1000)) / 1000)}s status=${response.status} rss=${rss?.toFixed(1)}MB`);
  await new Promise((done) => setTimeout(done, 5000));
}
child.stdin.end();
await new Promise((done) => child.once("exit", done));

const first = samples.find((value) => value !== null);
const last = [...samples].reverse().find((value) => value !== null);
if (first !== null && last !== null) {
  const growth = last - first;
  console.log(`rss first=${first.toFixed(1)}MB last=${last.toFixed(1)}MB growth=${growth.toFixed(1)}MB`);
  if (growth > Math.max(50, first * 0.5)) {
    console.error("soak failed: RSS growth above threshold");
    process.exit(1);
  }
}
