// The browser retains only nearby pages and visible cards, never the full library.
const Catalog = (() => {
  const PAGE = 160,
    MAX_PAGES = 8;
  let summary = null,
    model = null,
    initialized = false,
    previewSerial = 0,
    previewBase = 0,
    previewTotal = 0;
  let sidebarKey = "",
    tagRevision = "",
    flatFolders = [],
    folderDrawn = new Map(),
    folderCanvas;
  let recordMap = new Map();
  const client = crypto.randomUUID();
  function pagePins() {
    const counts = new Map();
    return {
      add(number) {
        counts.set(number, (counts.get(number) || 0) + 1);
      },
      delete(number) {
        const count = counts.get(number) || 0;
        if (count <= 1) counts.delete(number);
        else counts.set(number, count - 1);
      },
      has(number) {
        return counts.has(number);
      },
    };
  }
  function params() {
    return {
      root: state.root === null ? "" : String(state.root),
      folder: state.folder || "",
      recursive: $("#includeChildren").checked ? "1" : "0",
      view: state.view,
      kind: state.kind,
      tag: state.tag || "",
      search: state.search,
      sort: $("#sort").value,
    };
  }
  function get(id) {
    return recordMap.get(Number(id));
  }
  function remember(file, index, key) {
    let current = get(file.id);
    if (current) Object.assign(current, file);
    else {
      current = file;
      recordMap.set(file.id, current);
    }
    if (index !== undefined) {
      current.__catalogIndex = index;
      current.__catalogKey = key;
    }
    return current;
  }
  function syncFiles() {
    const retained = new Set(selection);
    for (const page of model?.pages.values() || [])
      for (const file of page) retained.add(file.id);
    for (const file of previewSequence || []) retained.add(file.id);
    for (const [id] of recordMap) if (!retained.has(id)) recordMap.delete(id);
    state.files = [...recordMap.values()]
      .filter(
        (file) => file.__catalogKey === model?.key || selection.has(file.id),
      )
      .sort((a, b) => (a.__catalogIndex ?? 0) - (b.__catalogIndex ?? 0));
  }
  function setup() {
    if (initialized) return;
    initialized = true;
    MaterialSelection.setup();
    const gallery = $("#gallery");
    gallery.addEventListener("scroll", () => schedule(), { passive: true });
    $("#folders").addEventListener("scroll", drawFolders, { passive: true });
    new ResizeObserver(() => {
      schedule();
      drawFolders();
    }).observe(gallery);
    document.addEventListener("sucaiyu-layout", () => {
      schedule();
      drawFolders();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") previewSerial++;
    });
  }
  function setSummary(data) {
    setup();
    summary = data;
    state.roots = data.roots;
    state.directories = data.directories;
    state.token = data.token;
  }
  async function page(current, number) {
    if (current.pages.has(number)) {
      const value = current.pages.get(number);
      current.pages.delete(number);
      current.pages.set(number, value);
      return value;
    }
    if (current.requests.has(number))
      return current.requests.get(number).promise;
    const controller = new AbortController(),
      abort = () => controller.abort();
    current.controller.signal.addEventListener("abort", abort, { once: true });
    const promise = (async () => {
      const query = new URLSearchParams({
        ...current.params,
        revision: current.revision,
        offset: String(number * PAGE),
        limit: String(PAGE),
      });
      const response = await fetch("/api/items?" + query, {
        signal: controller.signal,
      });
      const data = await response.json();
      if (response.status === 409) {
        const error = new Error(data.error);
        error.changed = true;
        throw error;
      }
      if (!response.ok) throw new Error(data.error || "素材列表读取失败");
      if (model !== current) return [];
      current.total = data.total;
      current.size = data.size;
      current.ready = true;
      const files = data.files.map((file, index) =>
        remember(file, number * PAGE + index, current.key),
      );
      current.pages.set(number, files);
      while (current.pages.size > MAX_PAGES)
        current.pages.delete(current.pages.keys().next().value);
      syncFiles();
      return files;
    })().finally(() => {
      current.controller.signal.removeEventListener("abort", abort);
      if (current.requests.get(number)?.controller === controller)
        current.requests.delete(number);
    });
    current.requests.set(number, { promise, controller });
    return promise;
  }
  function folders() {
    if (
      state.tag ||
      state.view === "favorite" ||
      state.view === "trash" ||
      $("#includeChildren").checked
    )
      return [];
    return LibraryFolders.children(
      state.roots,
      state.directories,
      state.root,
      state.folder,
      false,
    )
      .filter(
        (folder) =>
          !state.search ||
          folder.name.toLowerCase().includes(state.search.toLowerCase()),
      )
      .map((folder) => ({
        ...folder,
        count: folderCount(folder.root, folder.folder),
      }))
      .sort(folderCompare);
  }
  async function start() {
    setup();
    if (state.view === "trash") {
      suspend();
      renderTrashView();
      return;
    }
    document.body.classList.remove("trash-mode");
    $("#trashPanel").hidden = true;
    const query = params(),
      key = JSON.stringify([
        summary?.revision,
        query,
        $("#folderSort").value,
        thumbnailReloadVersion,
      ]);
    if (model?.key === key) {
      renderCatalogHeader(model.folders, model.total, model.ready);
      sidebar();
      draw(true);
      return;
    }
    const preserve =
        model && JSON.stringify(model.params) === JSON.stringify(query),
      scrollTop = preserve ? $("#gallery").scrollTop : 0;
    MaterialSelection.cancel();
    model?.controller.abort();
    stopHoverPreview();
    renderVersion++;
    thumbQueue = [];
    clearInfoQueue();
    observer?.disconnect();
    const gallery = $("#gallery");
    gallery.replaceChildren();
    gallery.scrollTop = 0;
    gallery.classList.add("virtual-gallery");
    const current = {
      key,
      params: query,
      revision: summary.revision,
      controller: new AbortController(),
      pages: new Map(),
      requests: new Map(),
      drawn: new Map(),
      total: 0,
      size: 0,
      folders: folders(),
      ready: false,
      frame: 0,
      protectedPages: pagePins(),
    };
    model = current;
    current.canvas = el("div", "virtual-canvas");
    gallery.append(current.canvas);
    observer = new IntersectionObserver(
      (entries) =>
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            observer.unobserve(entry.target);
            makeThumb(entry.target);
          }
        }),
      { root: gallery, rootMargin: "100px" },
    );
    if (!preserve) {
      selection.clear();
      state.selected = null;
      recordMap = new Map();
      state.files = [];
    } else syncFiles();
    renderCatalogHeader(current.folders, 0, false);
    sidebar();
    inspect();
    try {
      await page(current, 0);
      if (model !== current) return;
      renderCatalogHeader(current.folders, current.total, true);
      current.canvas.style.height = geometry().height + "px";
      gallery.scrollTop = scrollTop;
      draw(true);
      inspect();
    } catch (error) {
      if (error.name === "AbortError" || model !== current) return;
      if (error.changed) {
        await load();
        return;
      }
      current.ready = true;
      $("#status").textContent = error.message;
      renderCatalogHeader(current.folders, 0, true);
    }
  }
  function geometry() {
    const gallery = $("#gallery"),
      style = getComputedStyle(gallery),
      width = Math.max(
        120,
        gallery.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
      );
    return LibraryFolders.virtualWindow({
      total: (model?.folders.length || 0) + (model?.total || 0),
      width,
      height: gallery.clientHeight,
      scrollTop: gallery.scrollTop,
      tile: parseFloat(style.getPropertyValue("--tile")) || 170,
      list: gallery.classList.contains("list"),
      details: cardInfo.size || cardInfo.dimensions || cardInfo.duration,
    });
  }
  function schedule() {
    if (!model || model.frame) return;
    model.frame = requestAnimationFrame(() => {
      if (model) model.frame = 0;
      draw();
    });
  }
  function release(node) {
    const thumb = node.querySelector(".thumb");
    if (thumb) observer?.unobserve(thumb);
    if (activeHoverBox && node.contains(activeHoverBox)) stopHoverPreview();
    node.querySelectorAll("img,video").forEach((media) => {
      media.removeAttribute("src");
      media.load?.();
    });
    node.remove();
  }
  function draw(refresh = false) {
    const current = model;
    if (!current || state.view === "trash") return;
    const viewport = geometry();
    current.canvas.style.height = viewport.height + "px";
    for (const [index, node] of current.drawn)
      if (index < viewport.start || index >= viewport.end) {
        release(node);
        current.drawn.delete(index);
      }
    const required = new Set(),
      nearby = new Set(),
      visible = [];
    for (let index = viewport.start; index < viewport.end; index++) {
      const directory =
        index < current.folders.length ? current.folders[index] : null;
      const ordinal = index - current.folders.length,
        pageNumber = Math.floor(ordinal / PAGE);
      const file = directory
        ? null
        : current.pages.get(pageNumber)?.[ordinal % PAGE];
      if (!directory) {
        nearby.add(pageNumber);
        if (!file) required.add(pageNumber);
        else {
          const cached = current.pages.get(pageNumber);
          current.pages.delete(pageNumber);
          current.pages.set(pageNumber, cached);
        }
      }
      let node = current.drawn.get(index);
      const identity = directory
        ? "d:" + directory.root + ":" + directory.folder
        : file
          ? "f:" + file.id
          : "pending";
      if (!node || node.dataset.virtualIdentity !== identity) {
        if (node) release(node);
        node = directory
          ? createDirectoryCard(directory)
          : file
            ? createFileCard(file)
            : el("article", "card pending-card");
        node.dataset.virtualIdentity = identity;
        current.drawn.set(index, node);
        current.canvas.append(node);
      }
      Object.assign(node.style, {
        left:
          viewport.columnWidth * (index % viewport.columns) +
          viewport.gapX * (index % viewport.columns) +
          "px",
        top:
          Math.floor(index / viewport.columns) * viewport.stride -
          viewport.offsetY +
          "px",
        width: viewport.columnWidth + "px",
        height: viewport.cardHeight + "px",
      });
      if (file) {
        visible.push(file.id);
        if (refresh) queueInformation(file);
      }
    }
    MaterialSelection.render();
    pruneInfoQueue(visible);
    applyCardInformation();
    syncAudioCards();
    selectionStatus();
    window.materialSyncDragRegions?.();
    for (const [number, request] of current.requests)
      if (!nearby.has(number) && !current.protectedPages.has(number))
        request.controller.abort();
    for (const number of required)
      page(current, number)
        .then(() => {
          if (model === current) draw(true);
        })
        .catch((error) => {
          if (error.name === "AbortError" || model !== current) return;
          if (error.changed) {
            load().catch((error) => toast(error.message));
          } else $("#status").textContent = error.message;
        });
    prioritize(visible);
  }
  let focusTimer,
    lastFocus = "";
  function prioritize(ids) {
    const value = ids.join(",");
    if (value === lastFocus) return;
    lastFocus = value;
    clearTimeout(focusTimer);
    focusTimer = setTimeout(
      () => api("preview-focus", { client, ids }).catch(() => {}),
      150,
    );
  }
  function suspend() {
    MaterialSelection.cancel();
    model?.controller.abort();
    if (model) {
      for (const node of model.drawn.values()) release(node);
    }
    model = null;
    observer?.disconnect();
    previewSerial++;
  }
  function loaded() {
    return state.files.filter((file) => file.__catalogKey === model?.key);
  }
  function selected() {
    return [...selection].map(get).filter(Boolean);
  }
  async function open(file) {
    const current = model,
      request = ++previewSerial;
    remember(file);
    if (
      !current ||
      file.__catalogKey !== current.key ||
      file.__catalogIndex === undefined
    ) {
      previewBase = 0;
      previewTotal = 1;
      previewSequence = [file];
      preview(file, true);
      return;
    }
    const index = file.__catalogIndex,
      start = Math.max(0, Math.min(index - 20, current.total - 41)),
      end = Math.min(current.total, start + 41);
    const needed = [
      ...new Set([
        Math.floor(start / PAGE),
        Math.floor(Math.max(start, end - 1) / PAGE),
      ]),
    ];
    needed.forEach((number) => current.protectedPages.add(number));
    try {
      await Promise.all(needed.map((number) => page(current, number)));
      if (request !== previewSerial || current !== model) return;
      previewSequence = [];
      for (let ordinal = start; ordinal < end; ordinal++) {
        const item = current.pages.get(Math.floor(ordinal / PAGE))?.[
          ordinal % PAGE
        ];
        if (item) previewSequence.push(item);
      }
      previewBase = start;
      previewTotal = current.total;
      preview(file, true);
    } catch (error) {
      if (error.name !== "AbortError") toast(error.message);
    } finally {
      needed.forEach((number) => current.protectedPages.delete(number));
    }
  }
  function step(delta) {
    const selected = get(state.selected),
      index = selected?.__catalogIndex;
    if (index === undefined || !model) return;
    const next = index + delta;
    if (next < 0 || next >= model.total) return;
    const current = model,
      request = ++previewSerial,
      number = Math.floor(next / PAGE);
    current.protectedPages.add(number);
    page(current, number)
      .then((files) => {
        if (model === current && request === previewSerial)
          open(files[next % PAGE]);
      })
      .catch((error) => {
        if (error.name !== "AbortError") toast(error.message);
      })
      .finally(() => current.protectedPages.delete(number));
  }
  function previewFocus(file) {
    api("preview-focus", {
      client: client + ":preview",
      ids: file ? [file.id] : [],
    }).catch(() => {});
  }
  function previewPosition(index) {
    return {
      index: previewBase + index,
      total: previewTotal || previewSequence.length,
    };
  }
  function sidebar() {
    if (!summary) return;
    $("#total").textContent = summary.total;
    $("#favcount").textContent = summary.favorites;
    document
      .querySelectorAll("[data-view]")
      .forEach((button) =>
        button.classList.toggle(
          "active",
          button.dataset.view === state.view && !state.root && !state.tag,
        ),
      );
    const query = $("#folderSearch").value.trim().toLowerCase();
    const key = JSON.stringify([
      summary.revision,
      $("#folderSort").value,
      query,
      [...expandedFolders],
    ]);
    if (key !== sidebarKey) {
      const trees = new Map(
        state.roots.map((root) => [
          root.id,
          {
            name: pathBasename(root.path),
            root: root.id,
            path: null,
            count: root.count,
            children: new Map(),
          },
        ]),
      );
      for (const directory of state.directories) {
        if (directory.folder === ".") continue;
        let node = trees.get(directory.root),
          path = "";
        if (!node) continue;
        for (const part of directory.folder.split("/")) {
          path = path ? path + "/" + part : part;
          if (!node.children.has(part))
            node.children.set(part, {
              name: part,
              root: directory.root,
              path,
              count: folderCount(directory.root, path),
              children: new Map(),
            });
          node = node.children.get(part);
        }
      }
      const matches = new Map();
      const match = (node) => {
        const children = [...node.children.values()].map(match);
        const result =
          node.name.toLowerCase().includes(query) || children.some(Boolean);
        matches.set(node, result);
        return result;
      };
      if (query) for (const node of trees.values()) match(node);
      flatFolders = [];
      const walk = (node, depth) => {
        if (query && !matches.get(node)) return;
        flatFolders.push({ node, depth });
        if (query || expandedFolders.has(node.root + ":" + (node.path || "")))
          for (const child of [...node.children.values()].sort(folderCompare))
            walk(child, depth + 1);
      };
      for (const node of [...trees.values()].sort(folderCompare)) walk(node, 0);
      sidebarKey = key;
      const panel = $("#folders");
      panel.replaceChildren();
      folderCanvas = el("div", "folder-canvas");
      folderCanvas.style.height = flatFolders.length * 27 + "px";
      panel.append(folderCanvas);
      folderDrawn = new Map();
    }
    drawFolders();
    if (tagRevision !== summary.revision) {
      const panel = $("#tags");
      panel.replaceChildren();
      for (const item of summary.tags) {
        const button = el("button", "", "♧ " + item.tag + "　" + item.count);
        button.dataset.tag = item.tag;
        button.onclick = () => {
          state.tag = item.tag;
          state.root = null;
          state.folder = null;
          state.view = "all";
          state.kind = "all";
          state.search = "";
          $("#search").value = "";
          document
            .querySelectorAll("[data-kind]")
            .forEach((node) =>
              node.classList.toggle("selected", node.dataset.kind === "all"),
            );
          render();
        };
        panel.append(button);
      }
      if (!summary.tags.length)
        panel.append(el("span", "hint", "选中素材后，点击“打标签”"));
      tagRevision = summary.revision;
    }
    $("#tags")
      .querySelectorAll("button")
      .forEach((button) =>
        button.classList.toggle("active", button.dataset.tag === state.tag),
      );
  }
  function drawFolders() {
    if (!folderCanvas) return;
    const panel = $("#folders"),
      start = Math.max(0, Math.floor(panel.scrollTop / 27) - 5),
      end = Math.min(
        flatFolders.length,
        Math.ceil((panel.scrollTop + panel.clientHeight) / 27) + 5,
      );
    for (const [index, row] of folderDrawn)
      if (index < start || index >= end) {
        row.remove();
        folderDrawn.delete(index);
      }
    for (let index = start; index < end; index++) {
      const { node, depth } = flatFolders[index];
      let row = folderDrawn.get(index);
      if (!row) {
        row = el("div", "folder-row");
        row.dataset.root = node.root;
        row.style.paddingLeft = depth * 14 + "px";
        row.style.top = index * 27 + "px";
        const key = node.root + ":" + (node.path || ""),
          expanded =
            Boolean($("#folderSearch").value.trim()) ||
            expandedFolders.has(key);
        const toggle = el(
          "button",
          "tree-toggle",
          node.children.size ? (expanded ? "⌄" : "›") : "",
        );
        toggle.disabled = !node.children.size;
        toggle.setAttribute(
          "aria-label",
          (expanded ? "折叠" : "展开") + node.name,
        );
        toggle.onclick = () => {
          expanded ? expandedFolders.delete(key) : expandedFolders.add(key);
          sidebar();
        };
        const button = el("button", "folder-name", "▱ " + node.name);
        button.title = node.name;
        button.onclick = () => {
          state.root = node.root;
          state.folder = node.path;
          state.tag = null;
          state.view = "all";
          state.selected = null;
          selection.clear();
          render();
        };
        row.append(
          toggle,
          button,
          el("span", "folder-count", String(node.count)),
        );
        if (node.path === null) {
          const remove = el("button", "remove", "×");
          remove.title = "移除此索引（保留原文件）";
          remove.onclick = safe(async () => {
            await api("remove", { id: node.root });
            if (state.root === node.root) {
              state.root = null;
              state.folder = null;
            }
            await load();
          });
          row.append(remove);
        }
        folderDrawn.set(index, row);
        folderCanvas.append(row);
      }
      row
        .querySelector(".folder-name")
        .classList.toggle(
          "active",
          state.root === node.root && state.folder === node.path && !state.tag,
        );
    }
  }
  async function collect(indices, active) {
    const current = model;
    if (!current || !current.ready) return [];
    const groups = new Map();
    for (const index of indices) {
      const number = Math.floor(index / PAGE);
      if (!groups.has(number)) groups.set(number, []);
      groups.get(number).push(index % PAGE);
    }
    const work = [...groups],
      result = [];
    let cursor = 0;
    for (const [number] of work) current.protectedPages.add(number);
    try {
      const worker = async () => {
        while (cursor < work.length) {
          if (!active() || model !== current)
            throw new DOMException("Selection cancelled", "AbortError");
          const [number, offsets] = work[cursor++],
            files = await page(current, number);
          if (!active() || model !== current)
            throw new DOMException("Selection cancelled", "AbortError");
          for (const offset of offsets)
            if (files[offset]) result.push(files[offset]);
        }
      };
      await Promise.all([worker(), worker()]);
      return result.sort((a, b) => a.__catalogIndex - b.__catalogIndex);
    } finally {
      for (const [number] of work) current.protectedPages.delete(number);
    }
  }
  function retain(files) {
    for (const file of files) remember(file);
    syncFiles();
  }
  return {
    collect,
    retain,
    geometry,
    get key() {
      return model?.key;
    },
    get folderCount() {
      return model?.folders.length || 0;
    },
    setSummary,
    start,
    suspend,
    sidebar,
    folders,
    get,
    loaded,
    selected,
    open,
    step,
    previewFocus,
    previewPosition,
    schedule,
    client,
    get total() {
      return model?.total || 0;
    },
    get size() {
      return model?.size || 0;
    },
    get summary() {
      return summary;
    },
  };
})();
