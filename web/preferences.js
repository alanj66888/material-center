// Local appearance preferences and read-only previews of validated recycle-bin payloads.
const iconPaths = {
  original: "/app-icon.png",
  light: "/icon-light.png",
  dark: "/icon-dark.png",
};
let appearance = { theme: "system", icon: "dark" },
  trashPreviewGeneration = 0;
function applyAppearance() {
  const dark =
    appearance.theme === "dark" ||
    (appearance.theme === "system" &&
      matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelector(".brand .logo").src = iconPaths[appearance.icon];
  document.querySelector('link[rel="icon"]').href = iconPaths[appearance.icon];
  document
    .querySelectorAll("button[data-theme]")
    .forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.theme === appearance.theme),
      ),
    );
  document
    .querySelectorAll("[data-icon]")
    .forEach((b) =>
      b.setAttribute(
        "aria-pressed",
        String(b.dataset.icon === appearance.icon),
      ),
    );
  const payload = { theme: appearance.theme, icon: appearance.icon };
  window.webkit?.messageHandlers?.appearance?.postMessage(payload);
  window.desktopLibrary?.setAppearance?.(payload);
}
function saveAppearance() {
  try {
    localStorage.setItem(
      "materialCenter.appearance",
      JSON.stringify(appearance),
    );
  } catch {}
  applyAppearance();
}
function initializePreferences() {
  try {
    const saved = JSON.parse(localStorage.getItem("materialCenter.appearance"));
    if (["system", "light", "dark"].includes(saved?.theme))
      appearance.theme = saved.theme;
    if (Object.hasOwn(iconPaths, saved?.icon)) appearance.icon = saved.icon;
  } catch {}
  applyAppearance();
  matchMedia("(prefers-color-scheme: dark)").addEventListener(
    "change",
    applyAppearance,
  );
  $("#openSettings").onclick = () => $("#settings").showModal();
  $("#closeSettings").onclick = () => $("#settings").close();
  $("#settingsShared").onclick = () => {
    $("#settings").close();
    openSharedSettings();
  };
  document.querySelectorAll("button[data-theme]").forEach(
    (button) =>
      (button.onclick = () => {
        appearance.theme = button.dataset.theme;
        saveAppearance();
      }),
  );
  document.querySelectorAll("[data-icon]").forEach(
    (button) =>
      (button.onclick = () => {
        appearance.icon = button.dataset.icon;
        saveAppearance();
      }),
  );
  const section = $("#tagSection"),
    splitter = $("#tagsSplitter"),
    sidebar = document.querySelector(".sidebar");
  const resize = (height, remember = true) => {
    const available = Math.max(70, sidebar.clientHeight - 330);
    height = Math.round(Math.max(60, Math.min(available, height)));
    section.style.height = height + "px";
    splitter.setAttribute("aria-valuenow", height);
    if (remember)
      try {
        localStorage.setItem("materialCenter.tagsHeight", height);
      } catch {}
    document.dispatchEvent(new Event("sucaiyu-layout"));
  };
  let savedHeight;
  try {
    savedHeight = Number(localStorage.getItem("materialCenter.tagsHeight"));
  } catch {}
  resize(savedHeight || 180, false);
  splitter.onpointerdown = (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    splitter.focus();
    const start = event.clientY,
      height = section.getBoundingClientRect().height;
    splitter.setPointerCapture(event.pointerId);
    splitter.classList.add("dragging");
    document.body.classList.add("resizing-tags");
    splitter.onpointermove = (e) => resize(height + start - e.clientY);
    const end = () => {
      splitter.onpointermove = null;
      splitter.classList.remove("dragging");
      document.body.classList.remove("resizing-tags");
    };
    splitter.onpointerup = end;
    splitter.onpointercancel = end;
  };
  splitter.ondblclick = () => resize(180);
  splitter.onkeydown = (event) => {
    if (["ArrowUp", "ArrowDown", "Home"].includes(event.key)) {
      event.preventDefault();
      resize(
        event.key === "Home"
          ? 180
          : section.clientHeight + (event.key === "ArrowUp" ? 20 : -20),
      );
    }
  };
  window.addEventListener("resize", () => resize(section.clientHeight, false));
  $("#closeTrashPreview").onclick = () => $("#trashPreview").close();
  $("#trashPreview").addEventListener("close", () => {
    trashPreviewGeneration++;
    const node = $("#trashPlayer");
    node.querySelectorAll("video,audio").forEach((media) => {
      media.pause();
      media.removeAttribute("src");
      media.load();
    });
    node.replaceChildren();
  });
}
function trashPreviewURL(item, action) {
  return "/trash-preview/" + item.root + "/" + item.id + "/" + action;
}
async function openTrashPreview(item) {
  stopHoverPreview();
  const dialog = $("#trashPreview"),
    player = $("#trashPlayer");
  player.querySelectorAll("video,audio").forEach((media) => {
    media.pause();
    media.removeAttribute("src");
    media.load();
  });
  player.replaceChildren();
  const generation = ++trashPreviewGeneration,
    active = () => generation === trashPreviewGeneration && dialog.open;
  $("#trashPreviewName").textContent = item.name;
  $("#trashPreviewInfo").textContent =
    bytes(item.size) + " · 原位置：" + item.relative;
  $("#restorePreview").onclick = safe(async () => {
    trashSelected.clear();
    trashSelected.add(trashKey(item));
    dialog.close();
    await restoreMaterials();
  });
  if (!dialog.open) dialog.showModal();
  if (hasStaticPreview(item)) {
    const image = el("img");
    image.alt = item.name;
    image.src = webImageExtensions.has(item.ext)
      ? trashPreviewURL(item, "media")
      : trashPreviewURL(item, "poster");
    image.onerror = () => {
      if (active())
        player.replaceChildren(
          el("p", "hint", "此图像暂无法解码，原文件仍保留在回收站。"),
        );
    };
    player.append(image);
  } else if (["video", "audio"].includes(item.kind)) {
    const media = el(item.kind);
    media.controls = true;
    media.autoplay = true;
    media.playsInline = true;
    let attempted = false;
    const compatible = async () => {
      if (attempted || !active()) return;
      attempted = true;
      media.pause();
      media.removeAttribute("src");
      player.replaceChildren(
        el("p", "hint", "正在生成兼容预览，原文件保持不变…"),
      );
      try {
        const result = await api("trash-prepare", {
          root: item.root,
          id: item.id,
        });
        if (active()) {
          media.src = result.url;
          player.replaceChildren(media);
          media.play().catch(() => {});
        }
      } catch (error) {
        if (active())
          player.replaceChildren(
            el("p", "hint", "暂无法预览：" + error.message),
          );
      }
    };
    media.onerror = () => {
      if (item.kind === "video" && !attempted) compatible();
      else if (active())
        player.replaceChildren(
          el("p", "hint", "此编码暂无法预览，原文件仍保留在回收站。"),
        );
    };
    if (item.kind === "video" && !webVideoExtensions.has(item.ext))
      compatible();
    else {
      media.src = trashPreviewURL(item, "media");
      player.append(media);
      media.play().catch(() => {});
    }
  } else
    player.append(
      el(
        "p",
        "hint",
        "此文件类型暂无内置预览，可根据原位置、文件大小和标签判断是否还原。",
      ),
    );
  if (["image", "video", "audio"].includes(item.kind))
    fetch(trashPreviewURL(item, "metadata"))
      .then((r) => (r.ok ? r.json() : {}))
      .then((meta) => {
        if (active())
          $("#trashPreviewInfo").textContent = [
            bytes(item.size),
            meta.width && meta.height ? meta.width + " × " + meta.height : "",
            Number.isFinite(meta.duration) ? hoverClock(meta.duration) : "",
            "原位置：" + item.relative,
          ]
            .filter(Boolean)
            .join(" · ");
      })
      .catch(() => {});
}
