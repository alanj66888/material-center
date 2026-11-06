document.documentElement.dataset.platform =
  window.desktopLibrary?.platform ||
  (/Windows/.test(navigator.userAgent) ? "win32" : "mac");
const $ = (s) => document.querySelector(s);
const pathBasename = LibraryFolders.basename;
const state = {
  files: [],
  roots: [],
  directories: [],
  token: "",
  view: "all",
  kind: "all",
  root: null,
  folder: null,
  tag: null,
  selected: null,
  search: "",
};
const expandedFolders = new Set();
const initializedFolderRoots = new Set();
const nameOrder = new Intl.Collator("zh-CN", {
  numeric: true,
  sensitivity: "base",
});
const selection = new Set();
const folderCounts = new Map();
const folderSortModes = ["name-asc", "name-desc", "count-desc", "count-asc"];
try {
  const saved = localStorage.getItem("mediaLibrary.folderSort");
  if (folderSortModes.includes(saved)) $("#folderSort").value = saved;
} catch {}
function folderCompare(a, b) {
  return LibraryFolders.compareFolders(a, b, $("#folderSort").value);
}
function buildFolderCounts() {
  folderCounts.clear();
  for (const root of state.roots)
    folderCounts.set(JSON.stringify([root.id, null]), root.count || 0);
  for (const directory of state.directories)
    folderCounts.set(
      JSON.stringify([
        directory.root,
        directory.folder === "." ? null : directory.folder,
      ]),
      directory.count || 0,
    );
}
function folderCount(root, folder) {
  return folderCounts.get(JSON.stringify([root, folder])) || 0;
}
function fileById(id) {
  return Catalog.get(id);
}

let observer,
  toastTimer,
  renderVersion = 0,
  thumbnailReloadVersion = 0;
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}
function toast(text) {
  $("#toast").textContent = text;
  $("#toast").style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($("#toast").style.display = "none"), 3500);
}
async function api(path, data, retry = true) {
  let r;
  try {
    r = await fetch(
      "/api/" + path,
      data === undefined
        ? {}
        : {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Library-Token": state.token,
            },
            body: JSON.stringify(data),
          },
    );
  } catch {
    throw new Error("本地服务未运行，请退出并重新启动素材中心。");
  }
  const result = await r.json();
  if (r.status === 403 && retry && data !== undefined) {
    const d = await api("catalog");
    state.token = d.token;
    return api(path, data, false);
  }
  if (!r.ok) {
    const error = new Error(result.error || "操作失败");
    error.pending = Boolean(result.pending);
    throw error;
  }
  return result;
}
function safe(task) {
  return async (...args) => {
    try {
      await task(...args);
    } catch (e) {
      toast(e.message);
    }
  };
}
function bytes(n) {
  return n >= 1073741824
    ? (n / 1073741824).toFixed(2) + " GB"
    : n >= 1048576
      ? (n / 1048576).toFixed(1) + " MB"
      : Math.ceil(n / 1024) + " KB";
}
function tags(f) {
  return f.tags
    .split(/[,，]/)
    .map((x) => x.trim())
    .filter(Boolean);
}
async function load(renderView = true) {
  const d = await api("catalog");
  Catalog.setSummary(d);
  featureDataLoaded(d);
  if (state.view === "trash") {
    const bin = await api("trash");
    state.trashEntries = bin.items;
    $("#trashCount").textContent = bin.items.length;
  }
  for (const root of state.roots) {
    const identity = JSON.stringify([root.id, root.path]);
    if (!initializedFolderRoots.has(identity)) {
      expandedFolders.add(root.id + ":");
      initializedFolderRoots.add(identity);
    }
  }
  buildFolderCounts();
  sidebar();
  if (renderView) await render();
}
function directoryCards() {
  return Catalog.folders();
}

function enterFolder(d) {
  state.root = d.root;
  state.folder = d.folder;
  state.search = "";
  $("#search").value = "";
  state.selected = null;
  selection.clear();
  render();
}
function sidebar() {
  Catalog.sidebar();
}
function filtered() {
  return state.view === "trash" ? [] : Catalog.loaded();
}

function render() {
  document.body.classList.toggle("trash-mode", state.view === "trash");
  $("#trashPanel").hidden = state.view !== "trash";
  if (state.view === "trash") {
    stopHoverPreview();
    Catalog.suspend();
    renderTrashView();
    return Promise.resolve();
  }
  return Catalog.start();
}
function renderCatalogHeader(folders, total, ready) {
  const gallery = $("#gallery"),
    hasItems = total + folders.length > 0;
  const names = {
    all: "全部素材",
    favorite: "我的收藏",
    video: "视频素材",
    image: "图片素材",
    audio: "音频素材",
  };
  const rootName = pathBasename(
    state.roots.find((r) => r.id === state.root)?.path || "",
  );
  const title = state.tag
    ? "# " + state.tag
    : state.root
      ? rootName +
        (state.folder ? " / " + state.folder.split("/").join(" / ") : "")
      : names[state.view];
  $("#title").textContent = title;
  $("#libraryPath").title = state.root ? title + "（双击返回上一层）" : title;
  $("#libraryPath").setAttribute("aria-disabled", String(!state.root));
  $("#upFolder").disabled = !state.root;
  $("#count").textContent =
    total +
    " 个素材" +
    (folders.length ? " · " + folders.length + " 个文件夹" : "");
  $("#resultCount").textContent =
    "素材（" +
    total +
    "）" +
    (folders.length ? " · 文件夹（" + folders.length + "）" : "");
  $("#empty").hidden = !ready || hasItems;
  gallery.style.display = !ready || hasItems ? "" : "none";
  $("#empty h2").textContent = Catalog.summary.total
    ? "没有找到匹配的素材"
    : "把你的素材，连接起来";
  $("#empty p").textContent = Catalog.summary.total
    ? "试试其他关键词，或切换文件夹与筛选条件。"
    : "选择已经整理好的文件夹，即刻浏览视频、图片与音频。保留目录结构，原文件无需搬家。";
  $("#emptyAdd").hidden = Catalog.summary.total > 0;
}
function createDirectoryCard(d) {
  const card = el("article", "card directory-card");
  card.tabIndex = 0;
  card.setAttribute("aria-label", "文件夹 " + d.name);
  card.title = d.name;
  card.dataset.root = d.root;
  const thumb = el("div", "thumb");
  thumb.append(el("span", "folder-icon", "▰"));
  card.append(
    thumb,
    el("h3", "", d.name),
    el("small", "", d.count + " 个素材 · 双击打开"),
  );
  card.ondblclick = () => enterFolder(d);
  card.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      enterFolder(d);
    }
  };
  card.onclick = () => {
    MaterialSelection.cancel();
    state.selected = null;
    selection.clear();
    document
      .querySelectorAll(".card")
      .forEach((c) => c.classList.remove("selected"));
    card.classList.add("selected");
    inspect();
    $("#inspectTitle").textContent = d.name;
    selectionStatus();
  };
  return card;
}
function createFileCard(f) {
  const card = el("article", "card" + (selection.has(f.id) ? " selected" : ""));
  card.tabIndex = 0;
  card.dataset.id = f.id;
  card.dataset.root = f.root;
  card.setAttribute("aria-label", f.name);
  const thumb = el("div", "thumb");
  thumb.dataset.id = f.id;
  thumb.append(
    el(
      "span",
      "placeholder",
      f.kind === "video"
        ? "▷"
        : f.kind === "image"
          ? "▧"
          : f.kind === "audio"
            ? "♫"
            : "▤",
    ),
  );
  thumb.append(el("span", "badge", (f.ext || "FILE").toUpperCase()));
  const star = el(
    "button",
    "star" + (f.favorite ? " saved" : ""),
    f.favorite ? "★" : "☆",
  );
  star.title = "切换收藏";
  star.onclick = safe(async (e) => {
    e.stopPropagation();
    await update(f, { favorite: f.favorite ? 0 : 1 });
  });
  thumb.append(star);
  if (f.kind === "video") enableHoverScrub(thumb, f);
  if (f.kind === "audio") {
    thumb.append(el("span", "audio-play-hint", "▶ 单击试听"));
  }
  card.append(thumb, el("h3", "", f.name));
  const p = el("p");
  p.append(
    el("span", "", f.folder === "." ? "根目录" : f.folder),
    el("span", "", bytes(f.size)),
  );
  card.append(p);
  card.onclick = safe(async (e) => {
    if (!(await MaterialSelection.click(f, e))) return;
    inspect(f);
    if (
      f.kind === "audio" &&
      !e.metaKey &&
      !e.ctrlKey &&
      !e.shiftKey &&
      e.detail < 2
    )
      toggleAudioAudition(f);
  });
  card.ondblclick = () => preview(f);
  card.onkeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      preview(f);
    }
  };

  observer.observe(thumb);
  return card;
}

let thumbQueue = [],
  activeThumbs = 0;
function makeThumb(box) {
  thumbQueue.push({ box, version: renderVersion });
  drainThumbs();
}
function drainThumbs() {
  while (activeThumbs < 3 && thumbQueue.length) {
    const job = thumbQueue.shift();
    if (job.version !== renderVersion || !job.box.isConnected) continue;
    activeThumbs++;
    drawThumb(job.box).finally(() => {
      activeThumbs--;
      drainThumbs();
    });
  }
}
async function drawThumb(box) {
  const file = fileById(box.dataset.id);
  if (!file) return;
  queueInformation(file);
  if (hasStaticPreview(file) || file.kind === "video")
    loadServerPoster(box, file);
}

async function update(f, patch) {
  const next = { ...f, ...patch };
  const actual = await api("update", {
    id: f.id,
    ...patch,
    ...("tags" in patch ? { base_tags: f.tags } : {}),
  });
  Object.assign(f, next);
  if (actual.tags !== undefined) f.tags = actual.tags;
  await load(false);
  if ($("#preview").open) {
    $("#favoriteButton").textContent = f.favorite ? "★ 已收藏" : "☆ 加入收藏";
  } else render();
}
let previewSequence = [],
  previewStripObserver = null;
function unloadPlayer() {
  previewGeneration++;
  document.querySelectorAll("#player video,#player audio").forEach((v) => {
    v.pause();
    v.removeAttribute("src");
    v.load();
  });
  $("#player").replaceChildren();
}
function preview(f, keepSequence = false) {
  Catalog.previewFocus(f);
  notifyNativeSelection(f);
  pauseAudioAudition();
  stopHoverPreview();
  if (!keepSequence) {
    Catalog.open(f);
    return;
  }
  state.selected = f.id;
  selection.clear();
  selection.add(f.id);
  $("#previewName").textContent = f.name;
  $("#detailName").textContent = f.name;
  unloadPlayer();
  const player = $("#player");
  $("#metadata").replaceChildren();
  [
    ["类型", (f.ext || "FILE").toUpperCase()],
    ["大小", bytes(f.size)],
    ["修改时间", new Date(f.modified * 1000).toLocaleString("zh-CN")],
    ["原文件路径", f.path],
  ].forEach(([k, v]) =>
    $("#metadata").append(el("dt", "", k), el("dd", "", v)),
  );
  $("#favoriteButton").textContent = f.favorite ? "★ 已收藏" : "☆ 加入收藏";
  $("#favoriteButton").onclick = safe(() =>
    update(f, { favorite: f.favorite ? 0 : 1 }),
  );
  $("#tagInput").value = f.tags;
  $("#saveTags").onclick = safe(async () => {
    await update(f, { tags: $("#tagInput").value.trim() });
    toast("标签已保存");
  });
  $("#reveal").onclick = safe(() => api("reveal", { id: f.id }));
  $("#openExternal").onclick = safe(() => api("open", { id: f.id }));
  if (!$("#preview").open) $("#preview").showModal();
  queueInformation(f, true);
  refreshCardInformation(f);
  renderNearby(f, keepSequence);
  playPreviewMedia(f, player, previewGeneration);
}
function inspect(f) {
  notifyNativeSelection(f);
  if (activeHoverBox === $("#inspectCover")) stopHoverPreview();
  $("#inspectCover").onpointerenter = null;
  $("#inspectCover").onpointermove = null;
  $("#inspectCover").onpointerleave = null;
  const cover = $("#inspectCover");
  cover.replaceChildren();
  const title = $("#inspectTitle");
  title.textContent = f ? f.name : $("#title").textContent;
  if (f) {
    const source = document.querySelector(
      '.thumb[data-id="' +
        f.id +
        '"] img.poster-ready, .thumb[data-id="' +
        f.id +
        '"] img:not(.server-poster)',
    );
    if (source) {
      const img = el("img");
      img.src = source.src;
      img.alt = f.name;
      cover.append(img);
    } else
      cover.textContent =
        f.kind === "video"
          ? "▷"
          : f.kind === "image"
            ? "▧"
            : f.kind === "audio"
              ? "♫"
              : "▤";
  } else cover.textContent = "▱";
  const files = filtered();
  const rows = f
    ? [
        ["类型", (f.ext || "FILE").toUpperCase()],
        ["文件大小", bytes(f.size)],
        ["修改时间", new Date(f.modified * 1000).toLocaleString("zh-CN")],
        ["原文件路径", f.path],
      ]
    : [
        ["文件数量", String(Catalog.total)],
        ["文件总大小", bytes(Catalog.size)],
        [
          "所在位置",
          state.root
            ? (state.roots.find((r) => r.id === state.root)?.path || "") +
              (state.folder ? "/" + state.folder : "")
            : "本地资料库",
        ],
      ];
  const meta = $("#inspectMeta");
  meta.replaceChildren();
  rows.forEach(([k, v]) => meta.append(el("dt", "", k), el("dd", "", v)));
  $("#inspectActions").hidden = !f;
  if (!f) return;
  queueInformation(f, true);
  if (f.kind === "video") enableHoverScrub(cover, f);
  $("#inspectTagChips").replaceChildren(
    ...tags(f).map((t) => el("span", "tag-chip", t)),
  );
  $("#inspectFavorite").textContent = f.favorite ? "★ 已收藏" : "☆ 加入收藏";
  $("#inspectTags").value = f.tags;
  $("#inspectPreview").onclick = () => preview(f);
  $("#inspectFavorite").onclick = safe(() =>
    update(f, { favorite: f.favorite ? 0 : 1 }),
  );
  $("#inspectSave").onclick = safe(async () => {
    await update(f, { tags: $("#inspectTags").value.trim() });
    toast("标签已保存");
  });
  $("#inspectReveal").onclick = safe(() => api("reveal", { id: f.id }));
  $("#inspectOpen").onclick = safe(() => api("open", { id: f.id }));
}
function folderSearchChanged() {
  $("#clearFolderSearch").hidden = !$("#folderSearch").value;
  sidebar();
}
$("#folderSearch").oninput = folderSearchChanged;
$("#clearFolderSearch").onclick = () => {
  $("#folderSearch").value = "";
  folderSearchChanged();
  $("#folderSearch").focus();
};
$("#includeChildren").onchange = render;
function connect() {
  $("#connectError").textContent = "";
  $("#connect").showModal();
  $("#folderPath").focus();
}
$("#add").onclick = connect;
$("#emptyAdd").onclick = connect;
$("#closeConnect").onclick = () => $("#connect").close();
$("#closePreview").onclick = () => $("#preview").close();
$("#preview").addEventListener("close", () => {
  previewStripObserver?.disconnect();
  $("#nearbyStrip").replaceChildren();
  unloadPlayer();
  previewSequence = [];
  api("preview-focus", { client: Catalog.client + ":strip", ids: [] }).catch(
    () => {},
  );
  Catalog.previewFocus(null);
  render();
});
$("#choose").onclick = async () => {
  const b = $("#choose");
  b.disabled = true;
  $("#connectError").textContent = "";
  try {
    const d = window.desktopLibrary?.chooseFolder
      ? await window.desktopLibrary.chooseFolder()
      : await api("choose", {});
    if (d.path) $("#folderPath").value = d.path;
  } catch (e) {
    $("#connectError").textContent = e.message + " 也可以直接粘贴文件夹路径。";
  } finally {
    b.disabled = false;
  }
};
async function scanLibrary(path) {
  let job = await api("scan-start", { path });
  if ($("#connect").open) $("#connect").close();
  while (job.running) {
    $("#status").textContent =
      job.phase === "publishing"
        ? "正在更新索引，仍可浏览素材…"
        : "正在扫描：" +
          (job.files || 0).toLocaleString() +
          " 个文件 · " +
          (job.directories || 0).toLocaleString() +
          " 个文件夹";
    await new Promise((resolve) => setTimeout(resolve, 600));
    job = await api("scan-status?id=" + encodeURIComponent(job.id));
  }
  if (job.phase === "failed")
    throw new Error(job.error || "扫描失败，原索引已保留");
  $("#status").textContent = "";
  return { count: job.count };
}
$("#connectForm").onsubmit = async (e) => {
  e.preventDefault();
  const path = $("#folderPath").value.trim();
  if (!path) return;
  $("#scan").disabled = true;
  $("#scan").textContent = "正在扫描…";
  $("#connectError").textContent = "";
  try {
    const d = await scanLibrary(path);
    $("#connect").close();
    await load();
    toast(`扫描完成，共 ${d.count} 个素材`);
  } catch (e) {
    $("#connectError").textContent = e.message;
    toast(e.message);
  } finally {
    $("#scan").disabled = false;
    $("#scan").textContent = "连接并扫描";
  }
};
$("#refresh").onclick = safe(() => runLibraryMaintenance("scan", state.roots));
document.querySelectorAll("[data-view]").forEach(
  (b) =>
    (b.onclick = () => {
      state.view = b.dataset.view;
      state.root = null;
      state.folder = null;
      state.tag = null;
      state.kind = "all";
      document
        .querySelectorAll("[data-kind]")
        .forEach((b) =>
          b.classList.toggle("selected", b.dataset.kind === "all"),
        );
      if (state.view === "trash") load().catch((error) => toast(error.message));
      else render();
    }),
);
document.querySelectorAll("[data-kind]").forEach(
  (b) =>
    (b.onclick = () => {
      state.kind = b.dataset.kind;
      document
        .querySelectorAll("[data-kind]")
        .forEach((x) => x.classList.toggle("selected", x === b));
      render();
    }),
);
let searchTimer;
$("#search").oninput = (e) => {
  state.search = e.target.value;
  clearTimeout(searchTimer);
  searchTimer = setTimeout(render, 180);
};
$("#sort").onchange = render;
$("#scale").oninput = (e) => {
  $("#gallery").style.setProperty("--tile", e.target.value + "px");
  Catalog.schedule();
};
$("#listView").onclick = () => {
  $("#gallery").classList.add("list");
  $("#listView").classList.add("selected");
  $("#gridView").classList.remove("selected");
  Catalog.schedule();
};
$("#gridView").onclick = () => {
  $("#gallery").classList.remove("list");
  $("#gridView").classList.add("selected");
  $("#listView").classList.remove("selected");
  Catalog.schedule();
};
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "k") {
    e.preventDefault();
    $("#search").focus();
  }
  if (
    e.code === "Space" &&
    !["INPUT", "TEXTAREA", "SELECT", "BUTTON", "AUDIO", "VIDEO"].includes(
      document.activeElement.tagName,
    ) &&
    !document.querySelector("dialog[open]")
  ) {
    const f = filtered().find((f) => f.id === state.selected);
    if (f) {
      e.preventDefault();
      if (f.kind === "audio") toggleAudioAudition(f);
      else preview(f);
    }
  }
});
initializeFeatures();
initializePreferences();
load().catch((e) => toast("无法连接本地服务：" + e.message));

function selectedFiles() {
  return Catalog.selected();
}
function selectionStatus() {
  const n = selectedFiles().length;
  $("#recycleMaterials").disabled = !n || MaterialSelection.busy;
  $("#batchTags").disabled = !n || MaterialSelection.busy;
  $("#batchTags").textContent = n ? "打标签（" + n + "）" : "选中素材打标签";
}
$("#batchTags").onclick = () => {
  $("#batchInput").value = "";
  $("#tagError").textContent = "";
  $("#tagTarget").textContent =
    "为选中的 " + selectedFiles().length + " 个素材添加标签，保留已有标签。";
  $("#tagEditor").showModal();
  $("#batchInput").focus();
};
$("#closeTags").onclick = () => $("#tagEditor").close();
$("#tagForm").onsubmit = async (e) => {
  e.preventDefault();
  const add = [
    ...new Set(
      $("#batchInput")
        .value.split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ];
  if (!add.length) {
    $("#tagError").textContent = "请先输入至少一个标签";
    return;
  }
  $("#applyTags").disabled = true;
  try {
    const targets = selectedFiles();
    await api("tags", { ids: targets.map((f) => f.id), tags: add });
    $("#tagEditor").close();
    await load();
    toast("标签已保存，可点击左侧标签查找");
  } catch (e) {
    $("#tagError").textContent = e.message;
  } finally {
    $("#applyTags").disabled = false;
  }
};

function goParentFolder() {
  if (!state.root) return;
  if (!state.folder) {
    state.root = null;
  } else {
    const parts = state.folder.split("/");
    parts.pop();
    state.folder = parts.join("/") || null;
  }
  state.search = "";
  $("#search").value = "";
  state.selected = null;
  selection.clear();
  render();
}
$("#upFolder").onclick = goParentFolder;
$("#libraryPath").ondblclick = goParentFolder;
$("#libraryPath").onkeydown = (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    e.stopPropagation();
    goParentFolder();
  }
};

function setFolderSort(mode) {
  if (!folderSortModes.includes(mode)) return;
  $("#folderSort").value = mode;
  try {
    localStorage.setItem("mediaLibrary.folderSort", mode);
  } catch {}
  render();
}
$("#folderSort").onchange = () => setFolderSort($("#folderSort").value);

const contextMenu = $("#folderContextMenu");
let contextSource = null,
  contextRootId = null,
  maintenanceBusy = false;
const menuItems = [
  ...contextMenu.querySelectorAll("[role=menuitem],[role=menuitemradio]"),
];
const sortMenuButtons = [...contextMenu.querySelectorAll("[data-folder-sort]")];
sortMenuButtons.forEach((b) => b.setAttribute("aria-label", b.textContent));
function hideFolderMenu(restore = false) {
  if (contextMenu.hidden) return;
  contextMenu.hidden = true;
  if (restore && contextSource?.isConnected)
    contextSource.focus({ preventScroll: true });
}
function showFolderMenu(x, y, source) {
  MaterialSelection.cancel();
  MaterialSelection.render();
  contextRootId =
    Number(source.closest("[data-root]")?.dataset.root) || state.root || null;
  const clicked = source.closest(".card[data-id]");
  if (clicked && !selection.has(+clicked.dataset.id)) {
    selection.clear();
    selection.add(+clicked.dataset.id);
    state.selected = +clicked.dataset.id;
    document
      .querySelectorAll(".card[data-id]")
      .forEach((card) =>
        card.classList.toggle("selected", selection.has(+card.dataset.id)),
      );
    inspect(fileById(state.selected));
    selectionStatus();
  }
  $("#recycleSelection").disabled = !selectedFiles().length;
  $("#reloadLibraryView").disabled = maintenanceBusy;
  $("#rescanLibrary").disabled = maintenanceBusy || !state.roots.length;
  $("#rescanLibrary").textContent = contextRootId
    ? "⟳ 重新扫描所属素材库"
    : "⟳ 重新扫描全部素材库";
  contextSource = source;
  sortMenuButtons.forEach((b) => {
    const checked = b.dataset.folderSort === $("#folderSort").value;
    b.setAttribute("aria-checked", String(checked));
    b.tabIndex = checked ? 0 : -1;
  });
  contextMenu.hidden = false;
  contextMenu.style.left = "0px";
  contextMenu.style.top = "0px";
  const rect = contextMenu.getBoundingClientRect();
  contextMenu.style.left =
    Math.max(8, Math.min(x, innerWidth - rect.width - 8)) + "px";
  contextMenu.style.top =
    Math.max(8, Math.min(y, innerHeight - rect.height - 8)) + "px";
  sortMenuButtons
    .find((b) => b.getAttribute("aria-checked") === "true")
    .focus({ preventScroll: true });
}
for (const area of [$("#folders"), $("#gallery"), $("#empty")]) {
  area.tabIndex = area.tabIndex < 0 ? 0 : area.tabIndex;
  area.addEventListener("contextmenu", (e) => {
    if (document.querySelector("dialog[open]")) return;
    e.preventDefault();
    showFolderMenu(
      e.clientX,
      e.clientY,
      e.target.closest("button,article") || area,
    );
  });
  area.addEventListener("keydown", (e) => {
    if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {
      e.preventDefault();
      const rect = e.target.getBoundingClientRect();
      showFolderMenu(rect.left + 20, rect.top + 20, e.target);
    }
  });
}
sortMenuButtons.forEach(
  (b) =>
    (b.onclick = () => {
      hideFolderMenu(true);
      setFolderSort(b.dataset.folderSort);
    }),
);
contextMenu.addEventListener("keydown", (e) => {
  const enabled = menuItems.filter((b) => !b.disabled);
  const index = enabled.indexOf(document.activeElement);
  let next;
  if (e.key === "ArrowDown") next = (index + 1) % enabled.length;
  else if (e.key === "ArrowUp")
    next = (index + enabled.length - 1) % enabled.length;
  else if (e.key === "Home") next = 0;
  else if (e.key === "End") next = enabled.length - 1;
  if (next !== undefined) {
    e.preventDefault();
    enabled[next].focus();
  } else if (e.key === "Escape") {
    e.preventDefault();
    hideFolderMenu(true);
  } else if (e.key === "Tab") hideFolderMenu();
});
document.addEventListener("pointerdown", (e) => {
  if (!contextMenu.contains(e.target)) hideFolderMenu();
});
document.addEventListener(
  "scroll",
  (e) => {
    if (!contextMenu.contains(e.target)) hideFolderMenu();
  },
  true,
);
window.addEventListener("resize", () => hideFolderMenu());
window.addEventListener("blur", () => hideFolderMenu());

// Only one hover decoder runs at a time; leaving releases its file handle and buffer.
let activeHoverStop = null,
  activeHoverBox = null;
function stopHoverPreview() {
  if (activeHoverStop) activeHoverStop();
}
function hoverClock(seconds) {
  if (!Number.isFinite(seconds)) return "--:--";
  const n = Math.max(0, Math.floor(seconds));
  return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0");
}
function enableHoverScrub(box, file) {
  if (!webVideoExtensions.has(file.ext) && !file.compatible) {
    enableServerHover(box, file);
    return;
  }
  box.classList.add("scrub-capable");
  box.ondragstart = (e) => e.preventDefault();
  box.removeAttribute("title");
  let video = null,
    progress = null,
    label = null,
    enterTimer = null,
    seekTimer = null,
    latest = 0,
    lastSeek = 0,
    inside = false,
    stopped = true;
  const stop = () => {
    inside = false;
    stopped = true;
    clearTimeout(enterTimer);
    clearTimeout(seekTimer);
    if (video) {
      video.onloadedmetadata =
        video.onloadeddata =
        video.onseeked =
        video.onerror =
          null;
      video.pause();
      video.removeAttribute("src");
      video.load();
      video.remove();
      video = null;
    }
    progress?.remove();
    label?.remove();
    progress = label = null;
    box.classList.remove("scrub-active");
    if (activeHoverStop === stop) {
      activeHoverStop = null;
      activeHoverBox = null;
    }
  };
  const seek = () => {
    if (
      stopped ||
      !video ||
      !Number.isFinite(video.duration) ||
      video.duration <= 0
    )
      return;
    const target = LibraryFolders.scrubTime(latest, video.duration);
    label.textContent = hoverClock(target) + " / " + hoverClock(video.duration);
    progress.style.setProperty("--scrub-progress", latest * 100 + "%");
    if (video.seeking) return;
    const wait = 65 - (performance.now() - lastSeek);
    if (wait > 0) {
      clearTimeout(seekTimer);
      seekTimer = setTimeout(seek, wait);
      return;
    }
    if (Math.abs(video.currentTime - target) < 0.035 && video.readyState >= 2) {
      box.classList.add("scrub-active");
      return;
    }
    lastSeek = performance.now();
    try {
      video.currentTime = target;
    } catch {
      label.textContent = "此格式暂不支持滑动预览";
    }
  };
  const update = (e) => {
    if (e.pointerType === "touch") return;
    const rect = box.getBoundingClientRect();
    latest = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    if (inside) seek();
  };
  box.onpointerenter = (e) => {
    if (e.pointerType === "touch" || document.querySelector("dialog[open]"))
      return;
    stopHoverPreview();
    inside = true;
    stopped = false;
    activeHoverStop = stop;
    activeHoverBox = box;
    update(e);
    enterTimer = setTimeout(() => {
      if (!inside || !box.isConnected) return stop();
      video = el("video", "hover-video");
      video.muted = true;
      video.playsInline = true;
      video.preload = "metadata";
      video.setAttribute("aria-label", "滑动预览 " + file.name);
      progress = el("div", "scrub-progress");
      label = el("span", "scrub-time", "读取视频…");
      box.append(video, progress, label);
      video.onloadedmetadata = video.onloadeddata = seek;
      video.onseeked = () => {
        if (stopped) return;
        box.classList.add("scrub-active");
        if (
          Math.abs(
            video.currentTime -
              LibraryFolders.scrubTime(latest, video.duration),
          ) > 0.06
        )
          seek();
      };
      video.onerror = () => {
        if (stopped) return;
        box.classList.remove("scrub-active");
        label.textContent = "此格式暂不支持滑动预览";
      };
      video.src = mediaSource(file);
    }, 160);
  };
  box.onpointermove = update;
  box.onpointerleave = stop;
  box.onpointercancel = stop;
}
window.addEventListener("blur", stopHoverPreview);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopHoverPreview();
});

function renderNearby(current, focusCurrent = false) {
  previewStripObserver?.disconnect();
  const strip = $("#nearbyStrip");
  strip.replaceChildren();
  const index = previewSequence.findIndex((f) => f.id === current.id);
  const range = LibraryFolders.neighborRange(previewSequence.length, index);
  api("preview-focus", {
    client: Catalog.client + ":strip",
    ids: previewSequence.slice(range.start, range.end).map((file) => file.id),
  }).catch(() => {});
  const position = Catalog.previewPosition(index);
  $("#nearbyPosition").textContent =
    "附近素材 · " + (position.index + 1) + " / " + position.total;
  $("#previewPrevious").disabled = position.index <= 0;
  $("#previewNext").disabled = position.index >= position.total - 1;
  previewStripObserver = new IntersectionObserver(
    (entries) =>
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          previewStripObserver.unobserve(entry.target);
          makeThumb(entry.target);
        }
      }),
    { root: strip, rootMargin: "150px" },
  );
  previewSequence.slice(range.start, range.end).forEach((f) => {
    const button = el(
      "button",
      "nearby-item" + (f.id === current.id ? " active" : ""),
    );
    button.type = "button";
    button.title = f.name;
    button.setAttribute("aria-label", "预览 " + f.name);
    button.setAttribute("aria-current", String(f.id === current.id));
    const thumb = el("span", "thumb");
    thumb.dataset.id = f.id;
    const cached = document.querySelector(
      '#gallery .thumb[data-id="' +
        f.id +
        '"] img.poster-ready, #gallery .thumb[data-id="' +
        f.id +
        '"] img:not(.server-poster)',
    );
    if (cached) {
      const img = el("img");
      img.alt = "";
      img.src = cached.src;
      thumb.append(img);
    } else
      thumb.append(
        el(
          "span",
          "placeholder",
          f.kind === "video"
            ? "▷"
            : f.kind === "image"
              ? "▧"
              : f.kind === "audio"
                ? "♫"
                : "▤",
        ),
      );
    button.append(thumb, el("span", "nearby-name", f.name));
    button.onclick = () => preview(f, true);
    strip.append(button);
    if (!cached) previewStripObserver.observe(thumb);
  });
  const selected = strip.querySelector(".active");
  if (selected) {
    strip.scrollLeft = Math.max(
      0,
      selected.offsetLeft - strip.clientWidth / 2 + selected.clientWidth / 2,
    );
    if (focusCurrent && document.activeElement === document.body)
      selected.focus({ preventScroll: true });
  }
}
function stepPreview(delta) {
  Catalog.step(delta);
}

$("#previewPrevious").onclick = () => stepPreview(-1);
$("#previewNext").onclick = () => stepPreview(1);
$("#preview").addEventListener("keydown", (e) => {
  if (
    e.metaKey ||
    e.ctrlKey ||
    e.altKey ||
    e.shiftKey ||
    e.target.closest("input,textarea,select,video,audio")
  )
    return;
  if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
    e.preventDefault();
    stepPreview(e.key === "ArrowLeft" ? -1 : 1);
  }
});

async function runLibraryMaintenance(action, roots = []) {
  if (maintenanceBusy) return;
  if (action === "scan" && !roots.length) return connect();
  maintenanceBusy = true;
  $("#refresh").disabled = true;
  $("#reloadLibraryView").disabled = true;
  $("#rescanLibrary").disabled = true;
  $("#status").textContent =
    action === "scan"
      ? "正在重新扫描 " + roots.length + " 个素材库…"
      : "正在重新加载索引与当前视图缩略图…";
  try {
    const failures = [];
    let indexed = 0;
    if (action === "scan")
      for (let i = 0; i < roots.length; i++) {
        const root = roots[i];
        $("#status").textContent =
          "正在扫描（" + (i + 1) + " / " + roots.length + "）：" + root.path;
        try {
          const result = await scanLibrary(root.path);
          indexed += result.count;
        } catch (error) {
          failures.push(root.path + "：" + error.message);
        }
      }
    thumbnailReloadVersion = Date.now();
    thumbQueue = [];
    await load();
    if (failures.length) {
      $("#status").textContent = "扫描未全部完成：" + failures.join("；");
      toast("部分素材库扫描失败，详见上方提示。");
    } else {
      $("#status").textContent = "";
      toast(
        action === "scan"
          ? "扫描完成，共核对 " + indexed + " 个文件。"
          : "已重新加载，正在重试可见素材的缩略图。",
      );
    }
  } catch (error) {
    $("#status").textContent = error.message;
    throw error;
  } finally {
    maintenanceBusy = false;
    $("#refresh").disabled = false;
    $("#reloadLibraryView").disabled = false;
    $("#rescanLibrary").disabled = !state.roots.length;
  }
}
$("#reloadLibraryView").onclick = safe(async () => {
  hideFolderMenu();
  await runLibraryMaintenance("reload");
});
$("#rescanLibrary").onclick = safe(async () => {
  const roots = contextRootId
    ? state.roots.filter((r) => r.id === contextRootId)
    : [...state.roots];
  hideFolderMenu();
  await runLibraryMaintenance("scan", roots);
});

let audioAuditionFile = null;
const audioAuditionPlayer = $("#audioAuditionPlayer");
function syncAudioCards() {
  const playing =
    audioAuditionFile &&
    !audioAuditionPlayer.paused &&
    !audioAuditionPlayer.ended;
  document.querySelectorAll("#gallery .card").forEach((card) => {
    const active = playing && Number(card.dataset.id) === audioAuditionFile.id;
    card.classList.toggle("audio-playing", Boolean(active));
    const hint = card.querySelector(".audio-play-hint");
    if (hint) hint.textContent = active ? "Ⅱ 单击暂停" : "▶ 单击试听";
  });
}
function pauseAudioAudition() {
  audioAuditionPlayer.pause();
}
function toggleAudioAudition(file) {
  if (file.kind !== "audio") return;
  if (audioAuditionFile?.id === file.id && !audioAuditionPlayer.paused) {
    audioAuditionPlayer.pause();
    return;
  }
  if (audioAuditionFile?.id !== file.id) {
    audioAuditionPlayer.pause();
    audioAuditionFile = file;
    audioAuditionPlayer.src =
      "/media/" + file.id + "?modified=" + file.modified;
    $("#audioAuditionName").textContent = file.name;
    $("#audioAuditionName").title = file.path;
  }
  $("#audioAudition").hidden = false;
  $("#audioAuditionStatus").textContent = "正在加载…";
  if (audioAuditionPlayer.ended) audioAuditionPlayer.currentTime = 0;
  const playing = audioAuditionPlayer.play();
  if (playing)
    playing.catch((error) => {
      if (error.name === "AbortError") return;
      $("#audioAuditionStatus").textContent = "未能播放";
      if (error.name === "NotAllowedError")
        toast("请点击底部播放按钮开始试听。");
    });
}
audioAuditionPlayer.addEventListener("play", () => {
  $("#audioAuditionStatus").textContent = "正在试听 · 空格暂停";
  syncAudioCards();
});
audioAuditionPlayer.addEventListener("pause", () => {
  $("#audioAuditionStatus").textContent = "已暂停 · 空格继续";
  syncAudioCards();
});
audioAuditionPlayer.addEventListener("ended", () => {
  $("#audioAuditionStatus").textContent = "播放结束";
  syncAudioCards();
});
audioAuditionPlayer.addEventListener("error", () => {
  $("#audioAuditionStatus").textContent = "此格式无法试听，可用系统应用打开";
  syncAudioCards();
});
$("#closeAudioAudition").onclick = () => {
  audioAuditionPlayer.pause();
  audioAuditionPlayer.removeAttribute("src");
  audioAuditionPlayer.load();
  audioAuditionFile = null;
  $("#audioAudition").hidden = true;
  syncAudioCards();
};
$("#audioAuditionDetails").onclick = () => {
  if (audioAuditionFile) preview(audioAuditionFile);
};

function notifyNativeSelection(file) {
  const bridge = window.webkit?.messageHandlers?.selectedFile;
  if (bridge) bridge.postMessage({ path: file?.path || "" });
  const note = $("#fileDragNote");
  if (note)
    note.textContent =
      window.desktopLibrary?.platform === "win32"
        ? "可直接拖动素材缩略图到资源管理器或剪辑软件。"
        : bridge
          ? "可直接拖动素材缩略图，拖到 Finder 或剪辑软件。"
          : "拖放原文件请使用素材中心桌面版，或先在文件管理器中显示原文件。";
}

// Cache visible drag regions in AppKit before the mouse gesture begins.
if (window.webkit?.messageHandlers?.selectedFile) {
  const bridge = window.webkit.messageHandlers.selectedFile;
  let regionFrame = 0;
  const rectData = (node) => {
    const r = node.getBoundingClientRect();
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  };
  function syncDragRegions() {
    regionFrame = 0;
    if (document.querySelector("dialog[open]") && !$("#preview").open) {
      bridge.postMessage({ action: "regions", items: [], exclude: [] });
      return;
    }
    const modal = $("#preview").open;
    const nodes = modal
      ? document.querySelectorAll(
          "#previewName,#detailName,#nearbyStrip [data-id]",
        )
      : document.querySelectorAll(".card[data-id] .thumb,#inspectCover");
    const items = [];
    nodes.forEach((node) => {
      const card = node.closest("[data-id]");
      const file = fileById(card ? card.dataset.id : state.selected);
      const r = rectData(node);
      if (
        file &&
        r.width &&
        r.height &&
        r.x < innerWidth &&
        r.y < innerHeight &&
        r.x + r.width > 0 &&
        r.y + r.height > 0
      )
        items.push({ ...r, path: file.path });
    });
    const exclude = [
      ...document.querySelectorAll(
        "button,input,select,#player video,#player audio,#audioAudition audio",
      ),
    ]
      .filter((node) => !node.closest("#nearbyStrip"))
      .map(rectData)
      .filter((r) => r.width && r.height);
    bridge.postMessage({ action: "regions", items, exclude });
  }
  window.materialSyncDragRegions = syncDragRegions;
  const scheduleRegions = () => {
    if (!regionFrame) regionFrame = requestAnimationFrame(syncDragRegions);
  };
  document.addEventListener("scroll", scheduleRegions, true);
  window.addEventListener("resize", scheduleRegions);
  document.addEventListener("sucaiyu-layout", scheduleRegions);
  new MutationObserver(scheduleRegions).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["open", "hidden", "class"],
  });
  document.addEventListener("dragstart", (e) => e.preventDefault());
  scheduleRegions();
}

if (window.desktopLibrary?.platform === "win32") {
  document
    .querySelectorAll("#reveal,#inspectReveal")
    .forEach((button) => (button.textContent = "在资源管理器中显示"));
  document.addEventListener("dragstart", (e) => {
    const node = e.target.closest(
      ".thumb[data-id],.card[data-id],#inspectCover,#previewName,#detailName",
    );
    if (!node) return;
    const card = node.closest("[data-id]");
    const file = fileById(card ? card.dataset.id : state.selected);
    if (file) {
      e.preventDefault();
      window.desktopLibrary.startDrag(file.path);
    }
  });
  new MutationObserver(() => {
    document
      .querySelectorAll(
        ".card[data-id],.thumb[data-id],#inspectCover,#previewName,#detailName",
      )
      .forEach((node) => {
        if (!node.draggable) node.draggable = true;
      });
  }).observe(document.body, { childList: true, subtree: true });
}

(function enablePanelResize() {
  const defaults = () =>
    innerWidth >= 1600
      ? { left: 275, right: 245 }
      : innerWidth <= 1050
        ? { left: 205, right: 185 }
        : { left: 254, right: 222 };
  let preferred = defaults(),
    current,
    gesture = null;
  try {
    const saved = JSON.parse(localStorage.getItem("sucaiyu.panelWidths"));
    if (saved && Number.isFinite(saved.left) && Number.isFinite(saved.right))
      preferred = saved;
  } catch {}
  function apply(widths, active) {
    current = LibraryFolders.panelWidths(
      innerWidth,
      widths.left,
      widths.right,
      active,
    );
    document.body.style.setProperty("--sidebar-width", current.left + "px");
    document.body.style.setProperty("--inspector-width", current.right + "px");
    for (const [side, id] of [
      ["left", "leftSplitter"],
      ["right", "rightSplitter"],
    ]) {
      const handle = $("#" + id);
      const bound = LibraryFolders.panelWidths(
        innerWidth,
        side === "left" ? 600 : current.left,
        side === "right" ? 480 : current.right,
        side,
      );
      handle.setAttribute("aria-valuemin", side === "left" ? "160" : "180");
      handle.setAttribute("aria-valuemax", String(Math.round(bound[side])));
      handle.setAttribute("aria-valuenow", String(Math.round(current[side])));
    }
    document.dispatchEvent(new Event("sucaiyu-layout"));
  }
  function save() {
    preferred = { ...current };
    try {
      localStorage.setItem("sucaiyu.panelWidths", JSON.stringify(preferred));
    } catch {}
  }
  function finish(cancel = false) {
    if (!gesture) return;
    const { handle, id, original } = gesture;
    gesture = null;
    handle.classList.remove("dragging");
    document.body.classList.remove("resizing-panels");
    if (handle.hasPointerCapture(id)) handle.releasePointerCapture(id);
    if (cancel) apply(original);
    else save();
  }
  for (const [side, id] of [
    ["left", "leftSplitter"],
    ["right", "rightSplitter"],
  ]) {
    const handle = $("#" + id);
    handle.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      event.preventDefault();
      stopHoverPreview();
      gesture = {
        handle,
        id: event.pointerId,
        x: event.clientX,
        original: { ...current },
      };
      handle.setPointerCapture(event.pointerId);
      handle.classList.add("dragging");
      document.body.classList.add("resizing-panels");
    });
    handle.addEventListener("pointermove", (event) => {
      if (
        !gesture ||
        gesture.handle !== handle ||
        event.pointerId !== gesture.id
      )
        return;
      const delta = event.clientX - gesture.x;
      apply(
        {
          ...gesture.original,
          [side]: gesture.original[side] + (side === "left" ? delta : -delta),
        },
        side,
      );
    });
    handle.addEventListener("pointerup", () => finish());
    handle.addEventListener("pointercancel", () => finish(true));
    handle.addEventListener("lostpointercapture", () => finish(true));
    handle.addEventListener("dblclick", () => {
      apply({ ...current, [side]: defaults()[side] }, side);
      save();
    });
    handle.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        finish(true);
        return;
      }
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
        return;
      event.preventDefault();
      const delta =
        (event.key === "ArrowRight" ? 10 : -10) * (side === "left" ? 1 : -1);
      const width =
        event.key === "Home"
          ? side === "left"
            ? 160
            : 180
          : event.key === "End"
            ? side === "left"
              ? 600
              : 480
            : current[side] + delta;
      apply({ ...current, [side]: width }, side);
      save();
    });
  }
  window.addEventListener("resize", () => {
    finish(true);
    apply(preferred);
  });
  apply(preferred);
})();
