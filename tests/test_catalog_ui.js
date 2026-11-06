// Offline DOM integration: fetch is fully stubbed and external resources are disabled.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || "jsdom");
const root = path.resolve(__dirname, "..");
const errors = [],
  requests = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push(e));
const count = 120000;
const fixtureKind = process.env.CATALOG_FIXTURE_KIND || "other";
const summary = {
  revision: "fixture-1",
  version: "1.3.0",
  token: "offline",
  total: count,
  favorites: 0,
  total_size: count * 1024,
  tags: [],
  trash_count: 0,
  capabilities: {},
  roots: [{ id: 1, path: "/offline/素材库", count, size: count * 1024 }],
  directories: [
    { root: 1, folder: ".", count },
    { root: 1, folder: "A_大文件夹", count: 40000 },
    { root: 1, folder: "B_分类", count: 80000 },
  ],
};
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const scripts = [
  "library.js",
  "features.js",
  "preferences.js",
  "catalog.js",
  "selection.js",
  "app.js",
]
  .map((name) => fs.readFileSync(path.join(root, "web", name), "utf8"))
  .join("\n");
let html = fs
  .readFileSync(path.join(root, "web/index.html"), "utf8")
  .replace(/<script\b[^>]*>[\s\S]*?<\/script>/g, "");
html = html.replace(
  "</head>",
  "<style>" +
    fs.readFileSync(path.join(root, "web/style.css"), "utf8") +
    "</style></head>",
);
html = html.replace(
  "</body>",
  "<script>" +
    scripts.replace(/<\/script/gi, "<\\/script") +
    "</script></body>",
);
const dom = new JSDOM(html, {
  url: "https://offline.invalid/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(w) {
    Object.defineProperty(w.crypto, "randomUUID", { value: randomUUID });
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.ResizeObserver = class {
      observe() {}
      disconnect() {}
    };
    w.IntersectionObserver = class {
      constructor(fn) {
        this.fn = fn;
      }
      observe(node) {
        queueMicrotask(() => {
          if (node.isConnected)
            this.fn([{ target: node, isIntersecting: true }]);
        });
      }
      unobserve() {}
      disconnect() {}
    };
    Object.defineProperty(w.HTMLElement.prototype, "clientWidth", {
      get() {
        return this.id === "gallery" ? 800 : 254;
      },
    });
    Object.defineProperty(w.HTMLElement.prototype, "clientHeight", {
      get() {
        return this.id === "gallery" ? 600 : this.id === "folders" ? 360 : 800;
      },
    });
    w.HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    w.HTMLDialogElement.prototype.close = function () {
      this.open = false;
      this.dispatchEvent(new w.Event("close"));
    };
    w.HTMLMediaElement.prototype.pause = function () {};
    w.HTMLMediaElement.prototype.play = async function () {};
    w.HTMLMediaElement.prototype.load = function () {};
    w.fetch = async (url, options = {}) => {
      requests.push(String(url));
      const u = new URL(url, "https://offline.invalid/");
      let result;
      if (u.pathname === "/api/catalog") result = summary;
      else if (u.pathname === "/api/items") {
        await delay(8);
        if (options.signal?.aborted)
          throw new w.DOMException("Aborted", "AbortError");
        if (u.searchParams.get("revision") !== summary.revision)
          return {
            ok: false,
            status: 409,
            json: async () => ({ error: "Index changed" }),
          };
        const q = u.searchParams,
          offset = Number(q.get("offset")),
          limit = Number(q.get("limit"));
        const total = q.get("search")
          ? "0"
          : q.get("recursive") === "1"
            ? count
            : q.get("root") && q.get("folder") === "A_大文件夹"
              ? 40000
              : 0;
        result = {
          total: Number(total),
          size: Number(total) * 1024,
          offset,
          files: Array.from(
            { length: Math.max(0, Math.min(limit, Number(total) - offset)) },
            (_, i) => ({
              id: offset + i + 1,
              root: 1,
              folder: "A_大文件夹",
              name: "文件" + (offset + i + 1) + ".txt",
              path: "/offline/file" + (offset + i + 1),
              kind: fixtureKind,
              ext: fixtureKind === "video" ? "mp4" : "txt",
              size: 1024,
              modified: 100,
              tags: "",
              favorite: 0,
            }),
          ),
          revision: summary.revision,
        };
      } else if (u.pathname.startsWith("/api/metadata/"))
        result = { width: 1920, height: 1080, duration: 10, codec: "h264" };
      else if (u.pathname === "/api/preview-focus") result = { ok: true };
      else if (u.pathname === "/api/sync-tags")
        result = { changed: 0, trash_count: 0, errors: [] };
      else throw Error("Unexpected offline request " + url);
      return { ok: true, status: 200, json: async () => result };
    };
  },
});
const w = dom.window,
  ev = (code) => w.eval(code);
async function until(test, label) {
  for (let i = 0; i < 100; i++) {
    if (test()) return;
    await delay(15);
  }
  throw Error(
    "Timed out: " +
      label +
      "; " +
      w.document.querySelector("#toast").textContent +
      " " +
      errors.map((e) => e.message),
  );
}
(async () => {
  try {
    await until(
      () => w.document.querySelector(".directory-card"),
      "initial folders",
    );
    assert.equal(
      ev("state.files.length"),
      0,
      "homepage must not fetch every file",
    );
    ev(
      "state.root=1;document.querySelector('#includeChildren').checked=true;render()",
    );
    await until(
      () =>
        ev("Catalog.total") === count &&
        w.document.querySelector('[data-id="1"]'),
      "first page",
    );
    assert(
      w.document.querySelectorAll("#gallery .card").length < 60,
      "bounded visible cards",
    );
    assert.equal(ev("state.files.length"), 160);
    await ev("MaterialSelection.click(fileById(1),{})");
    await ev("MaterialSelection.click(fileById(10),{shiftKey:true})");
    assert.equal(ev("selection.size"), 10, "Shift selects a contiguous range");
    await ev("MaterialSelection.click(fileById(20),{ctrlKey:true})");
    await ev(
      "MaterialSelection.click(fileById(25),{shiftKey:true,ctrlKey:true})",
    );
    assert.equal(ev("selection.size"), 16, "Ctrl+Shift adds a range");
    await ev("MaterialSelection.click(fileById(160),{})");
    await ev("Catalog.collect([319],()=>true)");
    await ev("MaterialSelection.click(fileById(320),{shiftKey:true})");
    assert.equal(ev("selection.size"), 161, "Shift crosses page boundaries");
    await ev("Catalog.collect([6000],()=>true)");
    assert.equal(
      await ev("MaterialSelection.click(fileById(6001),{shiftKey:true})"),
      false,
      "oversized range is rejected",
    );
    assert.equal(
      ev("selection.size"),
      161,
      "rejected range leaves selection intact",
    );
    await ev("MaterialSelection.click(fileById(1),{})");
    await ev("Catalog.collect([3999],()=>true)");
    const cancelled = ev(
      "MaterialSelection.click(fileById(4000),{shiftKey:true})",
    );
    await ev("MaterialSelection.click(fileById(10),{})");
    await cancelled;
    assert.equal(
      ev("selection.size"),
      1,
      "a newer click cancels an older range request",
    );
    assert.equal(ev("state.selected"), 10);
    await ev("MaterialSelection.click(fileById(1),{})");
    const thumb = w.document.querySelector('#gallery .thumb[data-id="1"]');
    thumb.getBoundingClientRect = () => ({
      left: 0,
      right: 150,
      top: 30,
      bottom: 130,
      width: 150,
      height: 100,
    });
    ev(
      `loadServerPoster(document.querySelector('#gallery .thumb[data-id="1"]'),fileById(1))`,
    );
    const poster = thumb.querySelector(".server-poster");
    assert.equal(poster.alt, "");
    assert.equal(
      w.getComputedStyle(poster).visibility,
      "hidden",
      "pending image stays hidden",
    );
    poster.dispatchEvent(new w.Event("error"));
    assert.equal(
      w.getComputedStyle(poster).visibility,
      "hidden",
      "failed request never shows broken image",
    );
    poster.dispatchEvent(new w.Event("load"));
    assert.equal(w.getComputedStyle(poster).visibility, "visible");
    assert.equal(thumb.getAttribute("aria-busy"), "false");
    const rect = {
      left: 0,
      right: 800,
      top: 0,
      bottom: 600,
      width: 800,
      height: 600,
    };

    const gallery = w.document.querySelector("#gallery");
    gallery.getBoundingClientRect = () => rect;
    Object.defineProperty(gallery, "scrollHeight", {
      get() {
        return (
          parseFloat(gallery.querySelector(".virtual-canvas").style.height) ||
          600
        );
      },
    });
    const pointer = (type, x, y, extra = {}) => {
      const event = new w.Event(type, { bubbles: true, cancelable: true });
      Object.assign(event, {
        button: 0,
        pointerId: 1,
        isPrimary: true,
        clientX: x,
        clientY: y,
        ...extra,
      });
      gallery.dispatchEvent(event);
    };
    pointer("pointerdown", 8, 10);
    pointer("pointermove", 500, 100);
    pointer("pointerup", 500, 100);
    await until(
      () => ev("selection.size") === 3 && !ev("MaterialSelection.busy"),
      "marquee selects visible cards",
    );
    assert(
      !w.document.querySelector(".material-selection-box"),
      "selection overlay is removed",
    );
    const stride = ev("Catalog.geometry().stride");
    pointer("pointerdown", 8, stride + 5, { ctrlKey: true });
    pointer("pointermove", 100, stride + 50, { ctrlKey: true });
    pointer("pointerup", 100, stride + 50, { ctrlKey: true });
    await until(
      () => ev("selection.size") === 4 && !ev("MaterialSelection.busy"),
      "Ctrl marquee adds to selection",
    );
    pointer("pointerdown", 8, 10);
    pointer("pointermove", 500, 100);
    pointer("pointercancel", 500, 100);
    assert.equal(
      ev("selection.size"),
      4,
      "cancelled marquee retains committed selection",
    );
    pointer("pointerdown", 8, 10);
    pointer("pointermove", 500, 595);
    await delay(80);
    assert(gallery.scrollTop > 0, "marquee auto-scrolls near viewport edge");
    pointer("pointerup", 500, 595);
    await until(
      () => !ev("MaterialSelection.busy"),
      "auto-scroll selection commits",
    );
    assert(ev("selection.size") > 3);
    gallery.scrollTop = 0;
    gallery.dispatchEvent(new w.Event("scroll"));
    await delay(25);
    w.document.documentElement.dataset.platform = "win32";
    w.document.documentElement.dataset.theme = "light";
    const label = w.document.querySelector(".folder-row .folder-name");
    assert.equal(w.getComputedStyle(label).fontSize, "12.5px");
    assert.equal(w.getComputedStyle(label).fontWeight, "600");
    const checked = w.document.querySelector(
      '.context-menu [data-folder-sort="name-asc"]',
    );
    checked.setAttribute("aria-checked", "true");
    assert.equal(
      w.getComputedStyle(checked).backgroundColor,
      "rgb(231, 239, 250)",
      "light menu checked state stays light",
    );
    await ev("MaterialSelection.click(fileById(1),{})");

    for (let i = 1; i <= 25; i++) {
      gallery.scrollTop = i * 100000;
      gallery.dispatchEvent(new w.Event("scroll"));
      await delay(25);
    }
    await delay(80);
    assert(w.document.querySelectorAll("#gallery .card").length < 60);
    assert(
      ev("state.files.length") <= 1280 + ev("selection.size"),
      "bounded page cache",
    );
    assert(
      Number(w.document.querySelector("#gallery .card[data-id]")?.dataset.id) >
        10000,
      "deep scroll loads requested region",
    );
    ev("Catalog.open(Catalog.loaded()[0])");
    await until(
      () => w.document.querySelector("#preview").open,
      "open preview",
    );
    assert(ev("previewSequence.length") <= 41, "bounded nearby strip");
    w.document.querySelector("#preview").close();
    gallery.scrollTop = 0;
    gallery.dispatchEvent(new w.Event("scroll"));
    await until(() => w.document.querySelector('[data-id="1"]'), "return page");
    await ev("Catalog.open(fileById(160))");
    await ev("Catalog.step(1)");
    await until(() => ev("state.selected") === 161, "cross-page preview");
    w.document.querySelector("#preview").close();
    summary.revision = "fixture-2";
    await ev("load(false)");
    await ev("Catalog.open(fileById(320))");
    const staleRequest = new URL(
      requests.filter((url) => url.startsWith("/api/items")).at(-1),
      "https://offline.invalid/",
    );
    assert.equal(
      staleRequest.searchParams.get("revision"),
      "fixture-1",
      "an old page cache must request its original revision",
    );
    await ev("render()");
    ev("state.search='absent';render();state.search='';render()");
    await until(() => ev("Catalog.total") === count, "rapid filter changes");
    await delay(80);
    assert(ev("Catalog.total") === count);
    const oldCard = w.document.querySelector("#gallery .card[data-id]");
    await ev('runLibraryMaintenance("reload")');
    await until(
      () => w.document.querySelector("#gallery .card[data-id]") !== oldCard,
      "explicit thumbnail retry rebuilds cards",
    );
    ev(
      "state.root=1;state.folder=null;document.querySelector('#includeChildren').checked=false;setFolderSort('name-asc')",
    );
    await until(
      () => w.document.querySelectorAll(".directory-card").length === 2,
      "folder view",
    );
    assert(
      w.document
        .querySelector(".directory-card h3")
        .textContent.startsWith("A_"),
    );
    ev("setFolderSort('name-desc')");
    await until(
      () =>
        w.document
          .querySelector(".directory-card h3")
          ?.textContent.startsWith("B_"),
      "central folder sorting",
    );
    assert.equal(errors.length, 0, errors.map((e) => e.stack).join("\n"));
    console.log(
      JSON.stringify({
        records: count,
        kind: fixtureKind,
        visibleCards: w.document.querySelectorAll("#gallery .card").length,
        cachedFiles: ev("state.files.length"),
        requests: requests.length,
        checks:
          "paging, virtual scroll, cache bound, nearby preview, cross-page navigation, stale request cancellation",
      }),
    );
  } finally {
    w.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
