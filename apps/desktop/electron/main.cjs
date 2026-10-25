/**
 * Electron 主进程：spawn 引擎 → 读握手行 → 种 HttpOnly cookie → 加载 apps/web。
 * 父租约：stdin 保持打开；退出/崩溃时关 stdin，2s 后再 kill。
 */
const { app, BrowserWindow, Menu, Tray, nativeImage, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const ENGINE_STUDIO_ARGS = ["--studio-host"];
const PYTHON_ARGS = ["-m", "questorharness", ...ENGINE_STUDIO_ARGS];
const MAX_RESTARTS = 3;

let engine = null;
let window = null;
let tray = null;
let restarts = 0;
let quitting = false;

/** 引擎命令分派：QUESTOR_ENGINE 指向打包 exe 时参数直传；回退 python 时补 -m。 */
function engineCommand() {
  const target = process.env.QUESTOR_ENGINE;
  if (target) return { command: target, args: ENGINE_STUDIO_ARGS };
  return { command: "python", args: PYTHON_ARGS };
}

function validateHandshake(line) {
  let payload;
  try {
    payload = JSON.parse(line);
  } catch {
    throw new Error("handshake is not JSON");
  }
  const port = Number(payload.port);
  const token = typeof payload.token === "string" ? payload.token : "";
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error("bad handshake port");
  if (token.length < 32) throw new Error("handshake token is too short");
  return { port, token };
}

function readHandshake(child) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("handshake timeout")), 15000);
    const onData = (chunk) => {
      buffer += chunk.toString("utf8");
      const index = buffer.indexOf("\n");
      if (index < 0) return;
      clearTimeout(timer);
      child.stdout.off("data", onData);
      try {
        resolve(validateHandshake(buffer.slice(0, index)));
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

function spawnEngine() {
  const { command, args } = engineCommand();
  process.stderr.write(`[engine] spawn ${command} ${args.join(" ")}\n`);
  const child = spawn(command, args, {
    stdio: ["pipe", "pipe", "pipe"],
    env: process.env,
  });
  child.stderr.on("data", (chunk) => process.stderr.write(`[engine] ${chunk}`));
  child.once("exit", (code) => {
    if (quitting) return;
    if (restarts >= MAX_RESTARTS) {
      showFatal(`引擎已崩溃且重启次数耗尽（exit ${code}）`);
      return;
    }
    restarts += 1;
    showFatal(`引擎退出（exit ${code}），正在重启 ${restarts}/${MAX_RESTARTS}…`);
    setTimeout(() => void boot(), 500);
  });
  return child;
}

async function plantCookie(port, token) {
  await session.defaultSession.cookies.set({
    url: `http://127.0.0.1:${port}`,
    name: "questor_launch",
    value: token,
    httpOnly: true,
    sameSite: "strict",
  });
}

/** 窗口内错误/加载页：data URL 即可，不依赖引擎在线。 */
const LOADING_HTML = "data:text/html,<body style='font-family:system-ui;padding:2em'>Questor 启动中…</body>";
function fatalHtml(message) {
  const safe = String(message).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  return `data:text/html,<body style='font-family:system-ui;padding:2em;color:#b91c1c'>${safe}</body>`;
}
function showFatal(message) {
  window?.webContents.send("engine-crashed", message);
  if (window && !window.isDestroyed()) window.loadURL(fatalHtml(message)).catch(() => {});
}

/** 窗口先于引擎创建：Playwright/用户在任何引擎状态下都有窗口可寻（Reasonix starting-window 模式）。 */
function createWindow() {
  if (window) return window;
  window = new BrowserWindow({
    width: 1280,
    height: 800,
    frame: false,
    show: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false },
  });
  window.once("ready-to-show", () => window.show());
  window.on("close", (event) => {
    if (!quitting) {
      event.preventDefault();
      window.hide();
    }
  });
  window.webContents.setWindowOpenHandler(({ url }) => {
    void shell.openExternal(url);
    return { action: "deny" };
  });
  window.loadURL(LOADING_HTML).catch(() => {});
  return window;
}

async function boot() {
  createWindow();
  engine = spawnEngine();
  const { port, token } = await readHandshake(engine);
  await plantCookie(port, token);
  await window.loadURL(`http://127.0.0.1:${port}/`);
}

function shutdownEngine() {
  if (!engine) return;
  try {
    engine.stdin.end();
  } catch {
    /* already closed */
  }
  const child = engine;
  engine = null;
  setTimeout(() => {
    if (!child.killed) child.kill();
  }, 2000);
}

app.requestSingleInstanceLock();
app.on("second-instance", () => window?.show());

function createTray() {
  try {
    // 空图像在部分 Windows/CI 环境会抛异常并让进程提前退出：用 16x16 透明 PNG。
    const icon = nativeImage.createFromDataURL(
      "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAAXNSR0IArs4c6QAAAARnQU1BAACxjwv8YQUAAAAJcEhZcwAADsMAAA7DAcdvqGQAAAAOSURBVBhXY3jP4M/wHw0AAG6fBdkAAAAASUVORK5CYII=",
    );
    const created = new Tray(icon);
    created.setToolTip("Questor");
    created.on("click", () => window?.show());
    return created;
  } catch (error) {
    // 托盘是可选体验：无桌面会话时降级，不得阻断主窗口。
    process.stderr.write(`[tray] disabled: ${String(error)}\n`);
    return null;
  }
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null);
  tray = createTray();
  createWindow();
  try {
    await boot();
  } catch (error) {
    process.stderr.write(`[boot] failed: ${String(error)}\n`);
    showFatal(`引擎启动失败：${String(error)}`);
  }
});

app.on("before-quit", () => {
  quitting = true;
  shutdownEngine();
});

app.on("window-all-closed", (event) => event.preventDefault());

module.exports = { validateHandshake };
