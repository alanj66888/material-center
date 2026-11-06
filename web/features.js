// Shared tags, recycle bin and on-demand media information for the feature preview.
let cardInfo = {
  name: true,
  type: true,
  size: false,
  dimensions: false,
  duration: false,
};
const infoCache = new Map(),
  infoPending = new Set(),
  infoQueue = [];
let infoActive = 0,
  syncBusy = false,
  previewGeneration = 0;
const trashSelected = new Set();
const webImageExtensions = new Set(
  "jpg jpeg png gif webp bmp avif svg ico".split(" "),
);
const webVideoExtensions = new Set("mp4 m4v mov webm ogv".split(" "));

function hasStaticPreview(file) {
  return (
    file.kind === "image" ||
    [
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
      "xps",
      "oxps",
    ].includes(file.ext)
  );
}
function informationKey(file) {
  return file.id + ":" + file.modified + ":" + file.size;
}
function mediaSource(file) {
  return file.compatible ? "/compatible/" + file.id : "/media/" + file.id;
}
function mediaSummary(file) {
  const meta = infoCache.get(informationKey(file)) || file;
  const values = [];
  if (cardInfo.size) values.push(bytes(file.size));
  if (cardInfo.dimensions && meta.page_width && meta.page_height)
    values.push(meta.page_width + " × " + meta.page_height + " pt");
  else if (cardInfo.dimensions && ["image", "video"].includes(file.kind))
    values.push(
      meta.width && meta.height ? meta.width + " × " + meta.height : "尺寸 —",
    );
  if (cardInfo.duration && ["video", "audio"].includes(file.kind))
    values.push(
      Number.isFinite(meta.duration) ? hoverClock(meta.duration) : "时长 —",
    );
  return values.join(" · ");
}
function refreshCardInformation(file) {
  document
    .querySelectorAll('#gallery .card[data-id="' + file.id + '"] .card-meta')
    .forEach((node) => (node.textContent = mediaSummary(file)));
  if (state.selected === file.id) {
    for (const id of ["inspectMeta", "metadata"]) {
      const list = $("#" + id);
      list
        .querySelectorAll("[data-extra-meta]")
        .forEach((node) => node.remove());
      const meta = infoCache.get(informationKey(file));
      if (!meta) continue;
      const rows = [];
      if (meta.font_family) rows.push(["字体家族", meta.font_family]);
      if (meta.font_style) rows.push(["字体样式", meta.font_style]);
      if (meta.font_glyphs) rows.push(["字形数量", String(meta.font_glyphs)]);
      if (meta.page_count)
        rows.push(["页面", String(meta.page_count) + " 页 · 预览首页"]);
      if (meta.page_width && meta.page_height)
        rows.push([
          "页面尺寸",
          meta.page_width + " × " + meta.page_height + " pt",
        ]);
      if (meta.width && meta.height)
        rows.push(["尺寸", meta.width + " × " + meta.height]);
      if (Number.isFinite(meta.duration))
        rows.push(["时长", hoverClock(meta.duration)]);
      for (const [key, value] of rows) {
        const term = el("dt", "", key),
          detail = el("dd", "", value);
        term.dataset.extraMeta = "1";
        detail.dataset.extraMeta = "1";
        list.append(term, detail);
      }
    }
  }
}
function queueInformation(file, force = false) {
  if (
    !["image", "video", "audio"].includes(file.kind) &&
    !hasStaticPreview(file)
  )
    return;
  const key = informationKey(file);
  if (infoCache.has(key)) {
    Object.assign(file, infoCache.get(key));
    refreshCardInformation(file);
    return;
  }
  if (!force && !cardInfo.dimensions && !cardInfo.duration) return;
  if (infoPending.has(key)) return;
  infoPending.add(key);
  infoQueue.push(file);
  drainInformation();
}
function pruneInfoQueue(ids) {
  const visible = new Set(ids);
  for (let index = infoQueue.length - 1; index >= 0; index--) {
    const file = infoQueue[index];
    if (!visible.has(file.id) && file.id !== state.selected) {
      infoQueue.splice(index, 1);
      infoPending.delete(informationKey(file));
    }
  }
}
function clearInfoQueue() {
  for (const file of infoQueue) infoPending.delete(informationKey(file));
  infoQueue.length = 0;
}
function drainInformation() {
  while (infoActive < 3 && infoQueue.length) {
    const file = infoQueue.shift(),
      key = informationKey(file);
    infoActive++;
    api(
      "metadata/" +
        file.id +
        (typeof Catalog !== "undefined"
          ? "?client=" +
            Catalog.client +
            "&interactive=" +
            (file.id === state.selected ? 1 : 0)
          : ""),
    )
      .then((meta) => {
        if (infoCache.size >= 2000)
          infoCache.delete(infoCache.keys().next().value);
        if (meta.error) throw new Error(meta.error);
        infoCache.set(key, meta);
        Object.assign(file, meta);
        refreshCardInformation(file);
      })
      .catch((error) => {
        if (
          error.pending &&
          typeof Catalog !== "undefined" &&
          fileById(file.id) === file
        ) {
          file.__infoRetries = (file.__infoRetries || 0) + 1;
          if (file.__infoRetries <= 8)
            setTimeout(() => {
              if (fileById(file.id) === file)
                queueInformation(file, file.id === state.selected);
            }, 800);
        }
      })
      .finally(() => {
        infoPending.delete(key);
        infoActive--;
        drainInformation();
      });
  }
}
function applyCardInformation() {
  document.body.classList.toggle("hide-card-names", !cardInfo.name);
  document.body.classList.toggle("hide-card-types", !cardInfo.type);
  document.querySelectorAll("#gallery .card[data-id]").forEach((card) => {
    const file = fileById(card.dataset.id);
    if (!file) return;
    let detail = card.querySelector(".card-meta");
    if (!detail) {
      detail = el("div", "card-meta");
      card.append(detail);
    }
    detail.textContent = mediaSummary(file);
  });
}
function featureDataLoaded(data) {
  state.version = data.version;
  $("#settingsVersion").textContent =
    (data.version || "1.1 测试版") + (data.test_mode ? " · 功能测试" : "");
  state.trashCount = data.trash_count ?? state.trashCount ?? 0;
  state.capabilities = data.capabilities || {};
  $("#trashCount").textContent =
    data.trash_count === null ? "…" : state.trashCount;
  if (data.test_mode) {
    document.querySelector(".offline").textContent = "● 功能测试 · 独立资料库";
    if (!state.testDemoApplied) {
      Object.assign(cardInfo, { size: true, dimensions: true, duration: true });
      document
        .querySelectorAll("[data-card-info]")
        .forEach(
          (input) =>
            (input.checked = Boolean(cardInfo[input.dataset.cardInfo])),
        );
      state.testDemoApplied = true;
    }
  }
  const shared = state.roots.filter((root) => root.shared_tags);
  $("#sharedTags").textContent = shared.length
    ? "共享标签 · " + shared.length
    : "共享标签";
  $("#sharedTags").title = "连接同一层 NAS 素材库根目录，启用后跨电脑同步标签";
}
async function synchronizeShared(manual = false) {
  if (syncBusy || !state.roots.length || (!manual && document.hidden)) return;
  if (
    (!manual && document.activeElement?.closest("input,textarea")) ||
    (document.querySelector("dialog[open]") && !manual)
  )
    return;
  syncBusy = true;
  $("#syncTags").disabled = true;
  try {
    const result = await api("sync-tags", { force: manual });
    $("#trashCount").textContent = result.trash_count || 0;
    if (manual || result.changed || state.view === "trash") await load();
    if (result.errors.length) {
      $("#sharedTags").classList.add("sync-warning");
      $("#sharedTags").title = result.errors
        .map((item) => item.error)
        .join("\n");
      if (manual)
        toast(
          "部分素材库未同步：" +
            result.errors.map((item) => item.error).join("；"),
        );
    } else {
      $("#sharedTags").classList.remove("sync-warning");
      if (manual) toast("共享标签已同步");
    }
  } catch (error) {
    if (manual) toast(error.message);
  } finally {
    syncBusy = false;
    $("#syncTags").disabled = false;
  }
}
function openSharedSettings() {
  const panel = $("#sharedRoots");
  panel.replaceChildren();
  for (const root of state.roots) {
    const row = el("div", "shared-root-row");
    row.append(
      el("b", "", pathBasename(root.path)),
      el("small", "", root.path),
    );
    row.append(
      el(
        "p",
        "",
        root.shared_tags
          ? "已启用：其他电脑连接此根目录后会自动读取共享标签。"
          : "尚未启用：标签目前仅保存在这台电脑。",
      ),
    );
    if (root.sync_error) row.append(el("p", "inline-error", root.sync_error));
    const button = el(
      "button",
      "",
      root.shared_tags ? "立即同步" : "启用共享标签",
    );
    button.onclick = safe(async () => {
      button.disabled = true;
      try {
        if (!root.shared_tags) {
          if (
            !confirm(
              "将在此素材库中创建隐藏的共享标签记录，并合并现有标签。两台电脑必须连接同一层根目录。继续启用？",
            )
          )
            return;
          await api("shared-enable", { root: root.id });
        }
        await synchronizeShared(true);
        await load();
        openSharedSettings();
      } finally {
        button.disabled = false;
      }
    });
    row.append(button);
    panel.append(row);
  }
  if (!state.roots.length)
    panel.append(el("p", "hint", "请先连接素材文件夹。"));
  if (!$("#sharedSettings").open) $("#sharedSettings").showModal();
}
async function recycleMaterials() {
  const files = selectedFiles();
  if (!files.length) return;
  if (
    !confirm(
      "将 " +
        files.length +
        " 个原文件移入素材库回收站？\n可以还原，暂不释放存储空间。同一 NAS 上的其他电脑也会看到原位置的文件被移走。",
    )
  )
    return;
  stopHoverPreview();
  pauseAudioAudition();
  if ($("#preview").open) $("#preview").close();
  const result = await api("recycle", { ids: files.map((file) => file.id) });
  selection.clear();
  state.selected = null;
  await load();
  toast(
    "已移入回收站 " +
      result.processed.length +
      " 个" +
      (result.errors.length
        ? "；部分失败：" + result.errors.map((item) => item.error).join("；")
        : ""),
  );
}
function trashKey(item) {
  return item.root + ":" + item.id;
}
function selectedTrash() {
  return (state.trashEntries || []).filter((item) =>
    trashSelected.has(trashKey(item)),
  );
}
function trashSelectionStatus() {
  const count = selectedTrash().length;
  $("#restoreTrash").disabled = !count;
  $("#purgeTrash").disabled = !count;
  $("#restoreTrash").textContent = count
    ? "还原（" + count + "）"
    : "还原选中素材";
  $("#purgeTrash").textContent = count
    ? "彻底删除（" + count + "）"
    : "彻底删除选中素材";
}
function renderTrashView() {
  const cover = $("#inspectCover");
  cover.onpointerenter = null;
  cover.onpointermove = null;
  cover.onpointerleave = null;
  cover.onpointercancel = null;
  state.selected = null;
  selection.clear();
  notifyNativeSelection(null);
  $("#gallery").style.display = "none";
  $("#empty").hidden = true;
  $("#trashPanel").hidden = false;
  $("#title").textContent = "回收站";
  $("#libraryPath").title = "素材库回收站";
  $("#upFolder").disabled = true;
  const rows = (state.trashEntries || []).filter((item) =>
    [item.name, item.relative, item.root_name].some((value) =>
      value.toLowerCase().includes(state.search.toLowerCase()),
    ),
  );
  const list = $("#trashItems");
  list.replaceChildren();
  $("#trashSummary").textContent =
    "回收站 " + rows.length + " 个素材 · 还原前会检查同名文件，不会覆盖";
  $("#emptyTrash").disabled = !state.trashEntries?.length;
  for (const item of rows) {
    const card = el(
      "article",
      "trash-card" + (trashSelected.has(trashKey(item)) ? " selected" : ""),
    );
    card.tabIndex = 0;
    card.setAttribute("aria-label", "回收站素材 " + item.name);
    const thumb = el("div", "trash-thumb");
    if (hasStaticPreview(item) || item.kind === "video") {
      const image = el("img");
      image.alt = item.name;
      image.loading = "lazy";
      image.src = trashPreviewURL(item, "poster");
      image.onerror = () => {
        image.remove();
        thumb.append(
          el("span", "placeholder", item.kind === "video" ? "▷" : "▧"),
        );
      };
      thumb.append(image);
    } else
      thumb.append(
        el("span", "placeholder", item.kind === "audio" ? "♫" : "▤"),
      );
    card.append(thumb);
    if (item.kind === "video") enableTrashHover(thumb, item);
    card.ondblclick = () => openTrashPreview(item);
    card.append(
      el("span", "trash-format", (item.ext || "FILE").toUpperCase()),
      el("b", "", item.name),
      el("small", "", item.root_name + " / " + item.relative),
      el(
        "small",
        "",
        bytes(item.size) +
          " · " +
          new Date(item.deleted * 1000).toLocaleString("zh-CN"),
      ),
    );
    card.onclick = (event) => {
      if (event.metaKey || event.ctrlKey) {
        trashSelected.has(trashKey(item))
          ? trashSelected.delete(trashKey(item))
          : trashSelected.add(trashKey(item));
      } else {
        trashSelected.clear();
        trashSelected.add(trashKey(item));
      }
      for (const node of list.children)
        node.classList.toggle("selected", trashSelected.has(node.dataset.key));
      $("#inspectTitle").textContent = item.name;
      const cover = thumb.cloneNode(true);
      cover
        .querySelectorAll(".hover-video,.scrub-progress,.scrub-time")
        .forEach((node) => node.remove());
      cover.classList.remove("scrub-active");
      $("#inspectCover").replaceChildren(cover);
      if (item.kind === "video") enableTrashHover(cover, item);
      $("#inspectActions").hidden = true;
      $("#inspectMeta").replaceChildren();
      const previewButton = el("button", "", "预览回收站素材");
      previewButton.onclick = () => openTrashPreview(item);
      $("#inspectMeta").append(previewButton);
      for (const [key, value] of [
        ["原位置", item.root_path + "/" + item.relative],
        ["文件大小", bytes(item.size)],
        ["删除时间", new Date(item.deleted * 1000).toLocaleString("zh-CN")],
        ["标签", item.tags || "无"],
      ])
        $("#inspectMeta").append(el("dt", "", key), el("dd", "", value));
      trashSelectionStatus();
    };
    card.onkeydown = (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openTrashPreview(item);
      }
    };
    card.dataset.key = trashKey(item);
    list.append(card);
  }
  if (!rows.length)
    list.append(el("p", "hint", "回收站为空，或没有匹配的素材。"));
  $("#count").textContent = rows.length + " 个回收站素材";
  $("#inspectTitle").textContent = "回收站";
  $("#inspectCover").textContent = "♧";
  $("#inspectActions").hidden = true;
  $("#inspectMeta").replaceChildren();
  trashSelectionStatus();
  sidebar();
}
async function restoreMaterials() {
  const items = selectedTrash().map(({ root, id }) => ({ root, id }));
  if (!items.length) return;
  const result = await api("restore", { items });
  trashSelected.clear();
  await load();
  toast(
    "已还原 " +
      result.processed.length +
      " 个" +
      (result.errors.length
        ? "；未还原：" + result.errors.map((item) => item.error).join("；")
        : ""),
  );
}
async function purgeMaterials(all = false) {
  const items = (all ? state.trashEntries : selectedTrash()).map(
    ({ root, id }) => ({ root, id }),
  );
  if (!items.length) return;
  if (
    !confirm(
      "彻底删除回收站中的 " +
        items.length +
        " 个原文件？\n素材中心中将无法还原。NAS 自身的回收站或快照保留策略以 NAS 设置为准。",
    )
  )
    return;
  const result = await api("purge", {
    items,
    confirmation: "PERMANENTLY_DELETE",
  });
  trashSelected.clear();
  await load();
  toast(
    "已彻底删除 " +
      result.processed.length +
      " 个" +
      (result.errors.length
        ? "；部分失败：" + result.errors.map((item) => item.error).join("；")
        : ""),
  );
}
function loadServerPoster(box, file) {
  if (box.querySelector(".server-poster")) return;
  const image = el("img", "server-poster");
  image.alt = "";
  image.setAttribute("aria-label", file.name);
  box.classList.add("poster-loading");
  box.setAttribute("aria-busy", "true");
  image.decoding = "async";
  let attempts = 0;
  image.onload = () => {
    image.classList.add("poster-ready");
    box.classList.remove("poster-loading");
    box.setAttribute("aria-busy", "false");
    box.querySelector(".placeholder")?.remove();
    box.querySelector(".preview-note")?.remove();
  };
  const load = () => {
    const client =
      typeof Catalog !== "undefined"
        ? "&client=" +
          Catalog.client +
          (box.closest("#nearbyStrip") ? ":strip" : "")
        : "";
    image.src =
      "/preview-image/" +
      file.id +
      "?modified=" +
      file.modified +
      client +
      "&retry=" +
      attempts;
  };
  image.onerror = () => {
    image.classList.remove("poster-ready");
    if (!box.isConnected) return;
    const rect = box.getBoundingClientRect();
    if (attempts++ < 30 && rect.bottom > 0 && rect.top < innerHeight + 200) {
      setTimeout(
        () => {
          if (box.isConnected) load();
        },
        Math.min(4, attempts) * 500,
      );
    } else {
      image.remove();
      box.classList.remove("poster-loading");
      box.setAttribute("aria-busy", "false");
      if (!box.querySelector(".preview-note"))
        box.append(el("span", "preview-note", "预览暂不可用"));
    }
  };
  box.prepend(image);
  load();
}
async function prepareCompatible(file, active) {
  while (active()) {
    try {
      const result = await api("prepare", {
        id: file.id,
        async: true,
        client:
          typeof Catalog !== "undefined" ? Catalog.client + ":preview" : null,
      });
      if (!result.pending) return result;
    } catch (error) {
      if (!error.pending) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }
  throw new Error("预览已取消");
}

async function playPreviewMedia(file, player, generation) {
  const active = () => generation === previewGeneration && $("#preview").open;
  if (hasStaticPreview(file) && file.kind !== "image") {
    const image = el("img");
    image.alt = file.name;
    image.src = "/preview-image/" + file.id;
    image.onerror = () => {
      if (active())
        player.replaceChildren(
          el(
            "p",
            "preview-loading",
            "此文件暂无法生成预览，可用系统应用打开原文件。",
          ),
        );
    };
    player.append(image);
    return;
  }
  if (!["video", "audio", "image"].includes(file.kind)) {
    const panel = el("div", "unsupported-preview");
    panel.append(
      el("h2", "", (file.ext || "FILE").toUpperCase()),
      el("p", "", "此格式已收录，可打标签、搜索并用系统软件打开。"),
    );
    player.append(panel);
    return;
  }
  const media = el(
    file.kind === "image" ? "img" : file.kind === "audio" ? "audio" : "video",
  );
  let attempted = false;
  async function compatible() {
    if (attempted || !active()) return;
    attempted = true;
    media.pause?.();
    media.removeAttribute("src");
    player.replaceChildren(
      el(
        "p",
        "preview-loading",
        "正在生成兼容预览，首次需要等待。原文件保持不变，可先浏览其他素材。",
      ),
    );
    try {
      const result = await prepareCompatible(file, active);
      if (!active()) return;
      file.compatible = true;
      media.src = result.url;
      player.replaceChildren(media);
      media.play().catch(() => {});
    } catch (error) {
      if (active())
        player.replaceChildren(
          el(
            "p",
            "preview-loading",
            "无法生成此格式的兼容预览：" +
              error.message +
              "。可用系统应用打开原文件。",
          ),
        );
    }
  }
  media.onerror = () => {
    if (!active()) return;
    if (file.kind === "video" && !attempted && state.capabilities.ffmpeg)
      compatible();
    else
      player.replaceChildren(
        el(
          "p",
          "preview-loading",
          "此编码暂无法预览，可用系统应用打开原文件。",
        ),
      );
  };
  if (file.kind === "image") {
    media.alt = file.name;
    media.src = webImageExtensions.has(file.ext)
      ? "/media/" + file.id
      : "/preview-image/" + file.id;
    player.append(media);
  } else {
    media.controls = true;
    media.autoplay = true;
    media.playsInline = true;
    media.preload = "auto";
    if (
      file.kind === "video" &&
      !webVideoExtensions.has(file.ext) &&
      !file.compatible
    ) {
      await compatible();
      return;
    }
    media.src = mediaSource(file);
    player.append(media);
    media.play().catch(() => {});
  }
}
function enableTrashHover(box, item) {
  enableServerHover(box, item, {
    metadata: () =>
      fetch(trashPreviewURL(item, "metadata")).then(async (response) => {
        if (!response.ok) throw new Error("读取失败");
        return response.json();
      }),
    frame: (position) =>
      trashPreviewURL(item, "frame") + "?position=" + position,
  });
}
function enableServerHover(box, file, source = {}) {
  box.classList.add("scrub-capable");
  let inside = false,
    image,
    timer,
    progress,
    label,
    busy = false,
    latest = 0,
    last = -1;
  const stop = () => {
    inside = false;
    clearTimeout(timer);
    image?.remove();
    progress?.remove();
    label?.remove();
    box.classList.remove("scrub-active");
    if (activeHoverStop === stop) {
      activeHoverStop = null;
      activeHoverBox = null;
    }
  };
  const request = () => {
    if (!inside || busy || !box.isConnected) return;
    const position = Math.round(latest * 80);
    if (position === last) return;
    last = position;
    busy = true;
    label.textContent =
      hoverClock(latest * (file.duration || 0)) +
      " / " +
      hoverClock(file.duration);
    progress.style.setProperty("--scrub-progress", latest * 100 + "%");
    image.onload = () => {
      busy = false;
      if (inside) {
        box.classList.add("scrub-active");
        timer = setTimeout(request, 200);
      }
    };
    image.onerror = () => {
      busy = false;
      if (inside) {
        label.textContent = "此画面暂无法读取";
        last = -1;
        timer = setTimeout(request, 500);
      }
    };
    image.src = source.frame
      ? source.frame(position)
      : "/preview-frame/" +
        file.id +
        "?position=" +
        position +
        (typeof Catalog !== "undefined"
          ? "&client=" + Catalog.client + "&interactive=1"
          : "");
  };
  const update = (event) => {
    const rect = box.getBoundingClientRect();
    latest = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    if (inside) {
      clearTimeout(timer);
      timer = setTimeout(request, 200);
    }
  };
  box.onpointerenter = (event) => {
    if (event.pointerType === "touch" || document.querySelector("dialog[open]"))
      return;
    stopHoverPreview();
    inside = true;
    busy = false;
    last = -1;
    activeHoverStop = stop;
    activeHoverBox = box;
    update(event);
    image = el("img", "hover-video");
    progress = el("div", "scrub-progress");
    label = el("span", "scrub-time", "读取视频画面…");
    box.append(image, progress, label);
    (source.metadata ? source.metadata() : api("metadata/" + file.id))
      .then((meta) => {
        Object.assign(file, meta);
        if (inside) request();
      })
      .catch(() => {
        if (inside) label.textContent = "此格式暂无法预览";
      });
  };
  box.onpointermove = update;
  box.onpointerleave = stop;
  box.onpointercancel = stop;
}
function initializeFeatures() {
  try {
    Object.assign(
      cardInfo,
      JSON.parse(localStorage.getItem("sucaiyu.cardInfo")) || {},
    );
  } catch {}
  for (const input of document.querySelectorAll("[data-card-info]")) {
    input.checked = Boolean(cardInfo[input.dataset.cardInfo]);
    input.onchange = () => {
      cardInfo[input.dataset.cardInfo] = input.checked;
      try {
        localStorage.setItem("sucaiyu.cardInfo", JSON.stringify(cardInfo));
      } catch {}
      render();
    };
  }
  $("#sharedTags").onclick = openSharedSettings;
  $("#closeShared").onclick = () => $("#sharedSettings").close();
  $("#syncTags").onclick = () => synchronizeShared(true);
  $("#recycleSelection").onclick = safe(() => {
    hideFolderMenu();
    return recycleMaterials();
  });
  $("#recycleMaterials").onclick = safe(recycleMaterials);
  $("#restoreTrash").onclick = safe(restoreMaterials);
  $("#purgeTrash").onclick = safe(() => purgeMaterials(false));
  $("#emptyTrash").onclick = safe(() => purgeMaterials(true));
  document.addEventListener("keydown", (event) => {
    if (
      !["Delete", "Backspace"].includes(event.key) ||
      event.target.closest("input,textarea,select,button") ||
      document.querySelector("dialog[open]")
    )
      return;
    if (state.view !== "trash" && selectedFiles().length) {
      event.preventDefault();
      safe(recycleMaterials)();
    }
  });
  setInterval(() => synchronizeShared(false), 15000);
  setTimeout(() => synchronizeShared(false), 1500);
}
