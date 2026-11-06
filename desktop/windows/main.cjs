const {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  nativeImage,
  nativeTheme,
  session,
} = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

app.setName("素材中心");
app.setPath("userData", path.join(app.getPath("appData"), "素材屿"));
let window,
  backend,
  readyFile,
  baseURL,
  quitting = false,
  logDescriptor;

function trusted(event) {
  try {
    return (
      event.sender === window?.webContents &&
      new URL(event.senderFrame.url).origin === baseURL
    );
  } catch {
    return false;
  }
}

async function waitForBackend() {
  for (let attempt = 0; attempt < 600; attempt++) {
    if (backend.exitCode !== null)
      throw new Error("本地服务启动失败，请查看资料库目录中的 desktop.log。");
    try {
      const ready = JSON.parse(fs.readFileSync(readyFile, "utf8"));
      const url = new URL(ready.url);
      if (
        ready.app === "sucaiyu" &&
        url.protocol === "http:" &&
        url.hostname === "127.0.0.1"
      )
        return url.origin;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("本地服务启动超时，请退出后重新打开。");
}

async function start() {
  const data = app.getPath("userData");
  fs.mkdirSync(data, { recursive: true });
  readyFile = path.join(data, `session-${crypto.randomUUID()}.json`);
  logDescriptor = fs.openSync(path.join(data, "desktop.log"), "a");
  backend = spawn(
    path.join(process.resourcesPath, "python", "python.exe"),
    [
      "-X",
      "utf8",
      path.join(__dirname, "backend", "server.py"),
      "--no-browser",
      "--port",
      "8766",
      "--fallback-port",
      "--ready-file",
      readyFile,
    ],
    {
      windowsHide: true,
      env: { ...process.env, SUCAIYU_DATA_DIR: data },
      stdio: ["ignore", logDescriptor, logDescriptor],
    },
  );
  backend.on("error", (error) => {
    if (!quitting) {
      dialog.showErrorBox("素材中心", error.message);
      app.quit();
    }
  });
  baseURL = await waitForBackend();
  backend.on("exit", () => {
    if (!quitting) {
      dialog.showErrorBox("素材中心", "本地服务意外退出，请重新打开应用。");
      app.quit();
    }
  });

  window = new BrowserWindow({
    width: 1320,
    height: 850,
    minWidth: 960,
    minHeight: 600,
    title: "素材中心 · 本地素材库",
    backgroundColor: "#202020",
    autoHideMenuBar: true,
    icon: path.join(__dirname, "icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
      autoplayPolicy: "no-user-gesture-required",
    },
  });
  session.defaultSession.setPermissionRequestHandler(
    (_contents, _permission, callback) => callback(false),
  );
  session.defaultSession.setPermissionCheckHandler(() => false);
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => {
    if (new URL(url).origin !== baseURL) event.preventDefault();
  });
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    const permitted =
      details.url.startsWith(baseURL + "/") ||
      details.url.startsWith("data:") ||
      details.url.startsWith("blob:" + baseURL + "/");
    callback({ cancel: !permitted });
  });
  ipcMain.handle("choose-folder", async (event) => {
    if (!trusted(event)) throw new Error("请求来源无效");
    const result = await dialog.showOpenDialog(window, {
      title: "连接素材文件夹",
      properties: ["openDirectory"],
    });
    return { path: result.canceled ? "" : result.filePaths[0] };
  });
  ipcMain.on("set-appearance", (event, preferences) => {
    if (
      !trusted(event) ||
      !preferences ||
      !["system", "light", "dark"].includes(preferences.theme)
    )
      return;
    nativeTheme.themeSource = preferences.theme;
    const names = {
      original: "app-icon.png",
      light: "icon-light.png",
      dark: "icon-dark.png",
    };
    if (Object.hasOwn(names, preferences.icon)) {
      const image = nativeImage.createFromPath(
        path.join(__dirname, "backend", "web", names[preferences.icon]),
      );
      if (!image.isEmpty()) window.setIcon(image);
    }
  });
  const icon = nativeImage
    .createFromPath(path.join(__dirname, "icon.png"))
    .resize({ width: 48, height: 48 });
  ipcMain.on("drag-file", (event, file) => {
    if (!trusted(event) || typeof file !== "string" || !path.isAbsolute(file))
      return;
    try {
      if (!fs.statSync(file).isFile())
        throw new Error("原文件不存在或磁盘未连接。");
      event.sender.startDrag({ file, icon });
    } catch (error) {
      dialog.showErrorBox("无法拖出素材", error.message);
    }
  });
  await window.loadURL(baseURL + "/");
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  app
    .whenReady()
    .then(start)
    .catch((error) => {
      dialog.showErrorBox("素材中心启动失败", error.message);
      app.quit();
    });
}
app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  quitting = true;
  if (backend && backend.exitCode === null) {
    // Stop our backend and its decoders together; do not leave FFmpeg running.
    const stopped = spawnSync(
      path.join(
        process.env.SystemRoot || "C:\\Windows",
        "System32",
        "taskkill.exe",
      ),
      ["/PID", String(backend.pid), "/T", "/F"],
      { windowsHide: true, timeout: 5000 },
    );
    if (stopped.error || stopped.status !== 0) backend.kill();
  }
  if (readyFile) {
    try {
      fs.unlinkSync(readyFile);
    } catch {}
  }
  if (logDescriptor !== undefined) {
    try {
      fs.closeSync(logDescriptor);
    } catch {}
  }
});
