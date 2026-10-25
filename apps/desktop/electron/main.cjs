/**
 * Electron 主进程：spawn 引擎 → 读握手行 → 种 HttpOnly cookie → 加载 apps/web。
 * 父租约：stdin 保持打开；退出/崩溃时关 stdin，2s 后再 kill。
 */
const { app, BrowserWindow, Menu, Tray, nativeImage, session, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");

const ENGINE_ARGS = ["-m", "questorharness", "--studio-host"];
const MAX_RESTARTS = 3;

let engine = null;
let window = null;
let tray = null;
let restarts = 0;
let quitting = false;

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
  const command = process.env.QUESTOR_ENGINE || "python";
  const child = spawn(command, ENGINE_ARGS, {
    stdio: ["pipe", "pipe", "pipe"],
    env: process.env,
  });
  child.stderr.on("data", (chunk) => process.stderr.write(`[engine] ${chunk}`));
  child.once("exit", (code) => {
    if (quitting) return;
    if (restarts >= MAX_RESTARTS) {
      window?.webContents.send("engine-crashed", code);
      return;
    }
    restarts += 1;
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

async function boot() {
  engine = spawnEngine();
  const { port, token } = await readHandshake(engine);
  await plantCookie(port, token);
  if (!window) {
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
  }
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
  try {
    await boot();
  } catch (error) {
    process.stderr.write(`[boot] failed: ${String(error)}\n`);
    window?.webContents.send("engine-crashed", String(error));
  }
});

app.on("before-quit", () => {
  quitting = true;
  shutdownEngine();
});

app.on("window-all-closed", (event) => event.preventDefault());

module.exports = { validateHandshake };
