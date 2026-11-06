const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("desktopLibrary", {
  platform: "win32",
  chooseFolder: () => ipcRenderer.invoke("choose-folder"),
  setAppearance: (preferences) =>
    ipcRenderer.send("set-appearance", preferences),
  startDrag: (file) => ipcRenderer.send("drag-file", file),
});
