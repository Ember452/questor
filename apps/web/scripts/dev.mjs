/**
 * 一键开发编排：起引擎 → 读握手端口 → 注入 QUESTOR_STUDIO_ORIGIN → 起 Vite。
 * 退出时经父租约（stdin EOF）回收引擎。对应文档：计划 02 的"第一档开发循环"。
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "../../..");
/** vendored vite 配置固定 1420 且 strictPort=true：占用时必须显式换端口。 */
const PREFERRED_PORT = 1420;
/** 上次会话的进程登记：硬终止（taskkill/TerminateProcess）不走 exit 钩子，
 *  孤儿回收只能靠下次启动时"认领"——只杀自己登记过的 PID，陌生人不碰。 */
const PIDFILE = resolve(HERE, "../.dev-server.json");

function readPidfile() {
  try {
    return JSON.parse(fs.readFileSync(PIDFILE, "utf8"));
  } catch {
    return null;
  }
}

function isAlive(pid) {
  if (!Number.isInteger(pid)) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function portOwner(port) {
  const out = spawnSync("netstat", ["-ano"], { encoding: "utf8" }).stdout ?? "";
  for (const line of out.split("\n")) {
    // 形如 `TCP  [::1]:1420  [::]:0  LISTENING  10532`：状态在第 4 列，PID 在行尾；
    // 本地地址用 endsWith(`:port`) 防止 14200 误匹配 1420。
    const parts = line.trim().split(/\s+/);
    if (parts.length === 5 && parts[3] === "LISTENING" && parts[1].endsWith(`:${port}`)) {
      return Number(parts[4]);
    }
  }
  return null;
}

/** 回收上次登记的孤儿 vite（taskkill /F；引擎有父租约会自退，无需处理）。 */
function reclaimOrphanVite() {
  const record = readPidfile();
  if (!record) return false;
  const owner = portOwner(PREFERRED_PORT);
  if (owner === null || owner !== record.vitePid || !isAlive(owner)) return false;
  spawnSync("taskkill", ["/PID", String(owner), "/F"], { encoding: "utf8" });
  return true;
}

/** 端口空闲探测：vite 绑 localhost（IPv4+IPv6 双栈），只探一个栈会误判空闲。 */
function probeFree(port) {
  const tryBind = (host) =>
    new Promise((done) => {
      const server = net.createServer();
      server.once("error", () => done(false));
      server.listen(port, host, () => server.close(() => done(true)));
    });
  return Promise.all([tryBind("127.0.0.1"), tryBind("::1")]).then(
    ([v4, v6]) => v4 && v6,
  );
}

/** 首选端口被占时：先尝试认领回收，回收不了再挑空闲端口（strictPort 下显式传给 vite）。 */
async function pickPort() {
  if (await probeFree(PREFERRED_PORT)) return { port: PREFERRED_PORT, reclaimed: false };
  if (reclaimOrphanVite()) {
    for (let i = 0; i < 10; i += 1) {
      if (await probeFree(PREFERRED_PORT)) return { port: PREFERRED_PORT, reclaimed: true };
      await new Promise((done) => setTimeout(done, 200));
    }
  }
  return new Promise((done, reject) => {
    const fallback = net.createServer();
    fallback.listen(0, "127.0.0.1", () => {
      const { port } = fallback.address();
      fallback.close(() => done({ port, reclaimed: false }));
    });
    fallback.once("error", reject);
  });
}

/** 等 vite 真正握住端口（netstat 认到它的 PID）或退出——"ready"不许抢跑。 */
async function waitListening(child, port) {
  for (let i = 0; i < 50; i += 1) {
    if (child.exitCode !== null) return false;
    if (portOwner(port) === child.pid) return true;
    await new Promise((done) => setTimeout(done, 200));
  }
  return portOwner(port) === child.pid;
}

/** 读引擎握手行：{"port":N,"token":"..."}。 */
function readHandshake(child) {
  return new Promise((resolveLine, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("engine handshake timeout")), 30000);
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const index = buffer.indexOf("\n");
      if (index < 0) return;
      child.stdout.off("data", onData);
      try {
        const payload = JSON.parse(buffer.slice(0, index));
        if (!Number.isInteger(payload.port) || payload.port < 1) throw new Error("bad port");
        clearTimeout(timer);
        resolveLine(payload.port);
      } catch (error) {
        reject(error);
      }
    };
    child.stdout.on("data", onData);
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`engine exited before handshake (code ${code})`));
    });
  });
}

function prefixPipe(stream, label) {
  stream.on("data", (chunk) => {
    for (const line of chunk.toString("utf8").split("\n")) {
      if (line.trim()) process.stderr.write(`[${label}] ${line}\n`);
    }
  });
}

const engine = spawn(
  process.platform === "win32" ? "uv.exe" : "uv",
  ["run", "python", "-m", "questorharness", "--studio-host", "--serve-no-auth"],
  { cwd: REPO, stdio: ["pipe", "pipe", "pipe"] },
);
prefixPipe(engine.stderr, "engine");

let vite = null;
function cleanup() {
  if (!engine.killed) engine.stdin.end();
  try {
    fs.unlinkSync(PIDFILE);
  } catch {
    /* 不存在即无事 */
  }
}
// exit/SIGINT/SIGTERM 走优雅回收；硬终止（taskkill /F）钩子不执行，
// 孤儿由下次启动的 pidfile 认领兜底（reclaimOrphanVite）。
process.on("exit", () => {
  cleanup();
  if (vite && !vite.killed) vite.kill();
});
process.on("SIGINT", () => {
  cleanup();
  if (vite) vite.kill();
  process.exit(130);
});
process.on("SIGTERM", () => {
  cleanup();
  if (vite) vite.kill();
  process.exit(143);
});

try {
  const port = await readHandshake(engine);
  prefixPipe(engine.stdout, "engine");
  const { port: vitePort, reclaimed } = await pickPort();
  process.stderr.write(`[dev] engine ready: http://127.0.0.1:${port}\n`);
  if (reclaimed) {
    process.stderr.write(`[dev] reclaimed port ${PREFERRED_PORT} from an orphaned dev server\n`);
  } else if (vitePort !== PREFERRED_PORT) {
    process.stderr.write(`[dev] port ${PREFERRED_PORT} busy (not ours), using ${vitePort}\n`);
  }
  // Vite 直启（不经 npm 层），代理目标注入引擎回环 origin；strictPort 下显式给空闲端口。
  vite = spawn(
    process.execPath,
    [resolve(HERE, "../node_modules/vite/bin/vite.js"), "--port", String(vitePort)],
    {
      cwd: resolve(HERE, ".."),
      stdio: "inherit",
      env: { ...process.env, QUESTOR_STUDIO_ORIGIN: `http://127.0.0.1:${port}` },
    },
  );
  fs.writeFileSync(PIDFILE, JSON.stringify({ vitePid: vite.pid, enginePid: engine.pid, port: vitePort }));
  if (await waitListening(vite, vitePort)) {
    process.stderr.write(`[dev] web ready: http://localhost:${vitePort}\n`);
  } else {
    process.stderr.write(`[dev] vite failed to listen on ${vitePort}（输出见上方）\n`);
    cleanup();
    if (!vite.killed) vite.kill();
    process.exit(1);
  }
  const code = await new Promise((done) => vite.once("exit", done));
  cleanup();
  process.exit(code);
} catch (error) {
  console.error("dev failed:", error);
  cleanup();
  process.exit(1);
}
