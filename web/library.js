/* Shared pure directory navigation, also exercised by Node tests. */
(function (scope) {
  function basename(path) {
    return (
      path
        .split(String.fromCharCode(92))
        .join("/")
        .split("/")
        .filter(Boolean)
        .pop() || ""
    );
  }
  function children(roots, directories, root, folder, recursive) {
    if (recursive) return [];
    if (root === null)
      return roots.map((r) => ({
        root: r.id,
        folder: null,
        name: basename(r.path),
      }));
    const prefix = folder ? folder + "/" : "";
    const result = new Map();
    directories
      .filter((d) => d.root === root && d.folder !== ".")
      .forEach((d) => {
        if (!d.folder.startsWith(prefix)) return;
        const name = d.folder.slice(prefix.length).split("/")[0];
        if (name) result.set(name, { root, folder: prefix + name, name });
      });
    return [...result.values()];
  }
  function nameGroup(name) {
    const first = name.normalize("NFKC").trimStart();
    return /^[0-9]/.test(first)
      ? 0
      : /^[a-z]/i.test(first)
        ? 1
        : /^\p{Script=Han}/u.test(first)
          ? 2
          : 3;
  }
  const collator = new Intl.Collator("zh-CN", {
    numeric: true,
    sensitivity: "base",
  });
  function compareFolders(a, b, mode) {
    const name =
      nameGroup(a.name) - nameGroup(b.name) ||
      collator.compare(a.name.normalize("NFKC"), b.name.normalize("NFKC"));
    if (mode === "name-desc") return -name;
    if (mode === "count-desc") return (b.count || 0) - (a.count || 0) || name;
    if (mode === "count-asc") return (a.count || 0) - (b.count || 0) || name;
    return name;
  }
  function scrubTime(ratio, duration) {
    if (!Number.isFinite(duration) || duration <= 0) return 0;
    return (
      Math.max(0, Math.min(1, Number.isFinite(ratio) ? ratio : 0)) *
      Math.max(0, duration - 0.05)
    );
  }
  function neighborRange(length, index) {
    const start = Math.max(0, Math.min(index - 20, length - 41));
    return { start, end: Math.min(length, start + 41) };
  }
  function panelWidths(viewport, left, right, active) {
    const visibleRight = viewport > 720;
    const center = visibleRight
      ? 320
      : Math.min(320, Math.max(120, viewport - 192));
    const budget = Math.max(
      160 + (visibleRight ? 180 : 0),
      viewport - center - (visibleRight ? 12 : 6),
    );
    const finite = (value, fallback) =>
      Number.isFinite(value) ? value : fallback;
    left = Math.max(160, Math.min(600, finite(left, 254)));
    right = Math.max(180, Math.min(480, finite(right, 222)));
    if (visibleRight) {
      if (active === "left") {
        right = Math.min(right, budget - 160);
        left = Math.min(left, budget - right);
      } else {
        left = Math.min(left, budget - 180);
        right = Math.min(right, budget - left);
      }
    } else left = Math.min(left, budget);
    return { left, right };
  }
  function virtualWindow({
    total,
    width,
    height,
    scrollTop,
    tile = 170,
    list = false,
    details = false,
  }) {
    const columns = list
      ? 1
      : Math.max(1, Math.floor((width + 10) / (Math.min(tile, width) + 10)));
    const gapX = list ? 0 : 10,
      columnWidth = (width - gapX * (columns - 1)) / columns;
    const cardHeight = list
      ? 86
      : Math.ceil(
          5 +
            21 +
            ((columnWidth - 10) * 9) / 16 +
            12 +
            36 +
            4 +
            Math.max(18, details ? 39 : 0) +
            10 +
            2,
        );
    const stride = cardHeight + (list ? 5 : 24),
      rows = Math.ceil(total / columns);
    const fullHeight = Math.max(0, rows * stride - (list ? 5 : 24)),
      extent = Math.min(fullHeight, 8000000);
    scrollTop = Math.max(0, Math.min(scrollTop, Math.max(0, extent - height)));
    const virtualTop =
      fullHeight > extent
        ? (scrollTop * Math.max(0, fullHeight - height)) /
          Math.max(1, extent - height)
        : scrollTop;
    const first = Math.max(0, Math.floor(virtualTop / stride) - 2),
      last = Math.min(rows, Math.ceil((virtualTop + height) / stride) + 2);
    return {
      columns,
      columnWidth,
      cardHeight,
      stride,
      gapX,
      start: first * columns,
      end: Math.min(total, last * columns),
      height: extent,
      offsetY: virtualTop - scrollTop,
    };
  }
  function selectionIndices(
    rect,
    geometry,
    total,
    folderCount = 0,
    limit = 5000,
  ) {
    const result = [];
    const left = Math.min(rect.x1, rect.x2),
      right = Math.max(rect.x1, rect.x2);
    const top = Math.min(rect.y1, rect.y2),
      bottom = Math.max(rect.y1, rect.y2);
    const pitch = geometry.columnWidth + geometry.gapX;
    const firstColumn = Math.max(0, Math.floor(left / pitch)),
      lastColumn = Math.min(geometry.columns - 1, Math.floor(right / pitch));
    const firstRow = Math.max(
      0,
      Math.floor(top / geometry.stride),
      Math.floor(folderCount / geometry.columns),
    );
    const lastRow = Math.min(
      Math.ceil(total / geometry.columns) - 1,
      Math.floor(bottom / geometry.stride),
    );
    for (let row = firstRow; row <= lastRow; row++) {
      if (row * geometry.stride + geometry.cardHeight < top) continue;
      for (let column = firstColumn; column <= lastColumn; column++) {
        if (column * pitch + geometry.columnWidth < left) continue;
        const index = row * geometry.columns + column;
        if (index < folderCount || index >= total) continue;
        result.push(index - folderCount);
        if (result.length > limit) return { indices: result, overflow: true };
      }
    }
    return { indices: result, overflow: false };
  }
  const lib = {
    selectionIndices,
    virtualWindow,
    panelWidths,
    basename,
    children,
    compareFolders,
    scrubTime,
    neighborRange,
  };
  if (typeof module !== "undefined") module.exports = lib;
  else scope.LibraryFolders = lib;
})(typeof window !== "undefined" ? window : this);
