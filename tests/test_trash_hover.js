const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
test("recycle-bin hover uses its own payload frame URL and stops on leave", async () => {
  const requests = [],
    children = [];
  const make = () => ({
    style: { setProperty() {} },
    classList: { add() {}, remove() {} },
    remove() {},
  });
  const box = {
    isConnected: true,
    classList: { add() {}, remove() {} },
    getBoundingClientRect: () => ({ left: 100, width: 200 }),
    append(...nodes) {
      children.push(...nodes);
    },
  };
  const context = {
    Map,
    Set,
    setTimeout,
    clearTimeout,
    activeHoverStop: null,
    activeHoverBox: null,
    document: { querySelector: () => null },
    hoverClock: String,
    stopHoverPreview() {
      context.activeHoverStop?.();
    },
    trashPreviewURL: (item, action) =>
      `/trash-preview/${item.root}/${item.id}/${action}`,
    fetch: async (url) => {
      requests.push(url);
      return { ok: true, json: async () => ({ duration: 10 }) };
    },
    el: (tag) => {
      const node = make();
      if (tag === "img")
        Object.defineProperty(node, "src", {
          set(url) {
            requests.push(url);
            queueMicrotask(() => node.onload?.());
          },
        });
      return node;
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("web/features.js", "utf8"), context);
  context.enableTrashHover(box, { root: 4, id: "abc", kind: "video" });
  box.onpointerenter({ pointerType: "mouse", clientX: 150 });
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.ok(requests.includes("/trash-preview/4/abc/metadata"));
  assert.ok(requests.includes("/trash-preview/4/abc/frame?position=20"));
  box.onpointermove({ clientX: 280 });
  await new Promise((resolve) => setTimeout(resolve, 240));
  assert.ok(requests.includes("/trash-preview/4/abc/frame?position=72"));
  box.onpointerleave();
  assert.equal(context.activeHoverStop, null);
  const count = requests.length;
  box.onpointermove({ clientX: 100 });
  await new Promise((resolve) => setTimeout(resolve, 240));
  assert.equal(requests.length, count);
});

test("ordinary metadata queue works independently of hover preview sources", async () => {
  const requests = [];
  const context = {
    Map,
    Set,
    document: { querySelectorAll: () => [] },
    state: { selected: null },
    api: async (path) => {
      requests.push(path);
      return { width: 1920, height: 1080, duration: 3.5 };
    },
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("web/features.js", "utf8"), context);
  const file = { id: 10, kind: "video", modified: 1, size: 80 };
  context.queueInformation(file, true);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(requests, ["metadata/10"]);
  assert.equal(file.width, 1920);
  assert.equal(file.duration, 3.5);
  context.queueInformation(file, true);
  assert.equal(requests.length, 1);
});

test("fonts and vector documents have static previews even in older indexes", () => {
  const context = { Map, Set };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync("web/features.js", "utf8"), context);
  for (const ext of [
    "ttf",
    "otf",
    "ttc",
    "woff",
    "woff2",
    "pdf",
    "ai",
    "eps",
    "ps",
    "svg",
    "svgz",
  ]) {
    assert.equal(context.hasStaticPreview({ kind: "other", ext }), true, ext);
  }
  assert.equal(
    context.hasStaticPreview({ kind: "archive", ext: "zip" }),
    false,
  );
});
