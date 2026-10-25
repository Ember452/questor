/** 极简 preload：只暴露窗口控制与引擎崩溃事件，不暴露 Node。 */
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("questorHost", {
  minimize: () => ipcRenderer.send("window-minimize"),
  maximize: () => ipcRenderer.send("window-maximize"),
  close: () => ipcRenderer.send("window-close"),
  onEngineCrashed: (listener) => ipcRenderer.on("engine-crashed", (_event, code) => listener(code)),
});
