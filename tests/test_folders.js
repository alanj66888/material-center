const assert = require("node:assert/strict");
const { children } = require("../web/library.js");
const roots = [{ id: 1, path: "/素材库" }];
const dirs = [
  { root: 1, folder: "." },
  { root: 1, folder: "视频" },
  { root: 1, folder: "视频/航拍" },
  { root: 1, folder: "空目录" },
  { root: 2, folder: "无关" },
];
assert.deepEqual(children(roots, dirs, null, null, false), [
  { root: 1, folder: null, name: "素材库" },
]);
assert.deepEqual(
  children(roots, dirs, 1, null, false).map((x) => x.name),
  ["视频", "空目录"],
);
assert.deepEqual(children(roots, dirs, 1, "视频", false), [
  { root: 1, folder: "视频/航拍", name: "航拍" },
]);
assert.deepEqual(children(roots, dirs, 1, "空目录", false), []);
assert.deepEqual(children(roots, dirs, 1, null, true), []);
console.log("Folder navigation: 5 checks passed");
const { compareFolders } = require("../web/library.js");
const folders = [
  { name: "素材10", count: 3 },
  { name: "素材2", count: 5 },
  { name: "空文件夹", count: 0 },
  { name: "素材3", count: 5 },
];
const sort = (mode) => [...folders].sort((a, b) => compareFolders(a, b, mode));
assert.deepEqual(
  sort("name-asc")
    .filter((f) => f.name.startsWith("素材"))
    .map((f) => f.name),
  ["素材2", "素材3", "素材10"],
);
assert.deepEqual(sort("name-desc"), sort("name-asc").reverse());
assert.deepEqual(
  sort("count-desc").map((f) => f.count),
  [5, 5, 3, 0],
);
assert.deepEqual(
  sort("count-asc").map((f) => f.count),
  [0, 3, 5, 5],
);
assert.deepEqual(
  sort("count-desc")
    .slice(0, 2)
    .map((f) => f.name),
  ["素材2", "素材3"],
);
console.log("Folder sorting: 5 checks passed");
const { scrubTime } = require("../web/library.js");
assert.equal(scrubTime(-1, 10), 0);
assert.equal(scrubTime(0.5, 10), 4.975);
assert.equal(scrubTime(2, 10), 9.95);
assert.equal(scrubTime(0.5, Infinity), 0);
assert.equal(scrubTime(NaN, 10), 0);
console.log("Hover seek boundaries: 5 checks passed");
const { neighborRange } = require("../web/library.js");
assert.deepEqual(neighborRange(17, 0), { start: 0, end: 17 });
assert.deepEqual(neighborRange(100, 0), { start: 0, end: 41 });
assert.deepEqual(neighborRange(100, 50), { start: 30, end: 71 });
assert.deepEqual(neighborRange(100, 99), { start: 59, end: 100 });
console.log("Nearby strip windows: 4 checks passed");
const paths = require("../web/library.js");
assert.equal(paths.basename("C:\\素材\\视频库\\"), "视频库");
assert.equal(paths.basename("/Volumes/ExampleMedia/【素材库】"), "【素材库】");
assert.equal(
  paths.children([{ id: 8, path: "D:\\素材库" }], [], null, null, false)[0]
    .name,
  "素材库",
);
console.log("Windows and Mac path labels: 3 checks passed");
const mixed = [
  "样式雷",
  "B_县公路",
  "A_澄碧湖",
  "中科院",
  "C_活动",
  "原城纪",
  "a2_视频",
  "a10_视频",
  "Ａ_全角",
  "2024素材",
  "2023素材",
];
const mixedAsc = mixed
  .map((name) => ({ name }))
  .sort((a, b) => compareFolders(a, b, "name-asc"))
  .map((f) => f.name);
assert.deepEqual(mixedAsc.slice(0, 2), ["2023素材", "2024素材"]);
assert(mixedAsc.indexOf("A_澄碧湖") < mixedAsc.indexOf("B_县公路"));
assert(mixedAsc.indexOf("C_活动") < mixedAsc.indexOf("样式雷"));
assert(mixedAsc.indexOf("a2_视频") < mixedAsc.indexOf("a10_视频"));
assert(mixedAsc.indexOf("Ａ_全角") < mixedAsc.indexOf("中科院"));
assert.deepEqual(
  mixed
    .map((name) => ({ name }))
    .sort((a, b) => compareFolders(a, b, "name-desc"))
    .map((f) => f.name),
  [...mixedAsc].reverse(),
);
const { panelWidths } = require("../web/library.js");
assert.deepEqual(panelWidths(1665, 400, 300, "left"), {
  left: 400,
  right: 300,
});
for (const width of [640, 721, 800, 960, 1261, 1665])
  for (const side of ["left", "right", undefined]) {
    const result = panelWidths(width, 600, 480, side);
    assert(result.left >= 160 && result.left <= 600);
    assert(result.right >= 180 && result.right <= 480);
    if (width > 720) assert(result.left + result.right + 332 <= width);
    else assert(result.left + 326 <= width);
  }
assert.deepEqual(panelWidths(1261, NaN, Infinity), { left: 254, right: 222 });
console.log("Mixed folder names and resizable panel bounds passed");
const { virtualWindow } = require("../web/library.js");
for (const total of [0, 120000, 240000, 1000000])
  for (const list of [false, true]) {
    const first = virtualWindow({
      total,
      width: 800,
      height: 600,
      scrollTop: 0,
      list,
    });
    assert(first.end - first.start < 60);
    assert(first.height <= 8000000);
    const last = virtualWindow({
      total,
      width: 800,
      height: 600,
      scrollTop: Math.max(0, first.height - 600),
      list,
    });
    assert.equal(
      last.end,
      total,
      "last asset remains reachable past browser height limits",
    );
    assert(last.end - last.start < 60);
  }
console.log("Virtual grid/list bounds and final item reachability passed");
const { selectionIndices } = require("../web/library.js");
const geometry = {
  columns: 4,
  columnWidth: 100,
  gapX: 10,
  stride: 150,
  cardHeight: 120,
};
assert.deepEqual(
  selectionIndices({ x1: 5, x2: 225, y1: 5, y2: 180 }, geometry, 100, 0)
    .indices,
  [0, 1, 2, 4, 5, 6],
);
assert.deepEqual(
  selectionIndices({ x1: 225, x2: 5, y1: 180, y2: 5 }, geometry, 100, 0)
    .indices,
  [0, 1, 2, 4, 5, 6],
);
assert.deepEqual(
  selectionIndices({ x1: 105, x2: 108, y1: 125, y2: 140 }, geometry, 100)
    .indices,
  [],
  "gaps alone do not select cards",
);
assert.deepEqual(
  selectionIndices({ x1: 0, x2: 500, y1: 0, y2: 120 }, geometry, 10, 2).indices,
  [0, 1],
  "folders are excluded",
);
assert(
  selectionIndices({ x1: 0, x2: 500, y1: 0, y2: 1000000 }, geometry, 120000)
    .overflow,
  "huge rectangle is bounded",
);
console.log(
  "Marquee hit testing, reversed drag, gaps, folders and selection limits passed",
);
