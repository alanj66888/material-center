// Selection stores IDs; large ranges fetch bounded pages only when committed.
const MaterialSelection = (() => {
  const LIMIT = 5000;
  let serial = 0,
    anchor = null,
    pending = false,
    drag = null,
    overlay = null,
    frame = 0,
    initialized = false;
  function render() {
    let preview = null;
    if (drag?.started) {
      preview = new Set(drag.base);
      const indices = new Set(drag.hit.indices);
      for (const file of Catalog.loaded())
        if (indices.has(file.__catalogIndex)) preview.add(file.id);
    }
    for (const node of document.querySelectorAll("#gallery .card[data-id]")) {
      const chosen = (preview || selection).has(Number(node.dataset.id));
      node.classList.toggle("selected", chosen);
      node.setAttribute("aria-selected", String(chosen));
    }
  }
  function removeDrag() {
    cancelAnimationFrame(frame);
    frame = 0;
    if (drag) {
      try {
        $("#gallery").releasePointerCapture(drag.pointerId);
      } catch {}
    }
    drag = null;
    overlay?.remove();
    overlay = null;
    document.body.classList.remove("material-selecting");
  }
  function cancel() {
    serial++;
    pending = false;
    removeDrag();
    if (typeof selectionStatus === "function") selectionStatus();
  }
  async function commit(indices, base = new Set(), last = null) {
    const request = ++serial,
      key = Catalog.key;
    if (indices.length > LIMIT) {
      toast("单次最多选择 5000 个素材，请缩小选择范围。");
      return false;
    }
    pending = true;
    selectionStatus();
    try {
      const files = await Catalog.collect(
        indices,
        () => request === serial && Catalog.key === key,
      );
      if (request !== serial || Catalog.key !== key) return false;
      const chosen = new Set([...base, ...files.map((file) => file.id)]);
      if (chosen.size > LIMIT) {
        toast("单次最多选择 5000 个素材，请缩小选择范围。");
        return false;
      }
      selection.clear();
      for (const id of chosen) selection.add(id);
      Catalog.retain(files);
      state.selected = last ?? files.at(-1)?.id ?? [...chosen].at(-1) ?? null;
      render();
      inspect(state.selected ? Catalog.get(state.selected) : null);
      return true;
    } catch (error) {
      if (error.name !== "AbortError") toast(error.message);
      return false;
    } finally {
      if (request === serial) {
        pending = false;
        selectionStatus();
      }
    }
  }
  async function click(file, event) {
    cancel();
    const additive = event.ctrlKey || event.metaKey;
    if (event.shiftKey) {
      const first =
        anchor?.key === Catalog.key ? anchor.index : file.__catalogIndex;
      const start = Math.min(first, file.__catalogIndex),
        end = Math.max(first, file.__catalogIndex);
      if (end - start + 1 > LIMIT) {
        toast("单次最多选择 5000 个素材，请缩小选择范围。");
        return false;
      }
      if (!anchor || anchor.key !== Catalog.key)
        anchor = { key: Catalog.key, index: first };
      return commit(
        Array.from({ length: end - start + 1 }, (_, offset) => start + offset),
        additive ? new Set(selection) : new Set(),
        file.id,
      );
    }
    if (additive) {
      if (selection.has(file.id)) selection.delete(file.id);
      else if (selection.size < LIMIT) selection.add(file.id);
      else {
        toast("单次最多选择 5000 个素材。");
        return false;
      }
    } else {
      selection.clear();
      selection.add(file.id);
    }
    anchor = { key: Catalog.key, index: file.__catalogIndex };
    state.selected = file.id;
    render();
    selectionStatus();
    return true;
  }
  function point(event) {
    const gallery = $("#gallery"),
      bounds = gallery.getBoundingClientRect(),
      geometry = Catalog.geometry(),
      style = getComputedStyle(gallery);
    const x = Math.max(
      0,
      Math.min(
        gallery.clientWidth -
          parseFloat(style.paddingLeft) -
          parseFloat(style.paddingRight),
        event.clientX - bounds.left - parseFloat(style.paddingLeft),
      ),
    );
    const y =
      gallery.scrollTop +
      geometry.offsetY +
      Math.max(0, Math.min(gallery.clientHeight, event.clientY - bounds.top));
    return { x, y, geometry, bounds, padding: parseFloat(style.paddingLeft) };
  }
  function update() {
    if (!drag?.started) return;
    const current = point(drag.event);
    drag.rect = {
      x1: drag.origin.x,
      y1: drag.origin.y,
      x2: current.x,
      y2: current.y,
    };
    drag.hit = LibraryFolders.selectionIndices(
      drag.rect,
      current.geometry,
      Catalog.total + Catalog.folderCount,
      Catalog.folderCount,
      LIMIT,
    );
    const x1 = Math.min(drag.rect.x1, drag.rect.x2),
      x2 = Math.max(drag.rect.x1, drag.rect.x2);
    const top = Math.max(
      current.bounds.top,
      Math.min(drag.rect.y1, drag.rect.y2) -
        $("#gallery").scrollTop -
        current.geometry.offsetY +
        current.bounds.top,
    );
    const bottom = Math.min(
      current.bounds.top + $("#gallery").clientHeight,
      Math.max(drag.rect.y1, drag.rect.y2) -
        $("#gallery").scrollTop -
        current.geometry.offsetY +
        current.bounds.top,
    );
    Object.assign(overlay.style, {
      left: current.bounds.left + current.padding + x1 + "px",
      top: top + "px",
      width: x2 - x1 + "px",
      height: Math.max(0, bottom - top) + "px",
    });
    render();
  }
  function autoScroll() {
    frame = 0;
    if (!drag?.started) return;
    const gallery = $("#gallery"),
      bounds = gallery.getBoundingClientRect(),
      y = drag.event.clientY;
    const velocity =
      y < bounds.top + 30
        ? -Math.min(18, (bounds.top + 30 - y) / 2)
        : y > bounds.bottom - 30
          ? Math.min(18, (y - bounds.bottom + 30) / 2)
          : 0;
    if (velocity) {
      gallery.scrollTop = Math.max(
        0,
        Math.min(
          gallery.scrollTop + velocity,
          gallery.scrollHeight - gallery.clientHeight,
        ),
      );
      Catalog.schedule();
      update();
    }
    frame = requestAnimationFrame(autoScroll);
  }
  function down(event) {
    if (
      event.button !== 0 ||
      event.isPrimary === false ||
      state.view === "trash" ||
      document.querySelector("dialog[open]") ||
      event.target.closest(
        ".card:not(.pending-card),button,input,select,a,video,audio",
      ) ||
      !Catalog.key
    )
      return;
    const gallery = $("#gallery"),
      bounds = gallery.getBoundingClientRect();
    if (event.clientX >= bounds.left + gallery.clientWidth) return;
    cancel();
    drag = {
      pointerId: event.pointerId,
      event,
      origin: point(event),
      screen: { x: event.clientX, y: event.clientY },
      base: event.ctrlKey || event.metaKey ? new Set(selection) : new Set(),
      started: false,
    };
    try {
      gallery.setPointerCapture(event.pointerId);
    } catch {}
  }
  function move(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    drag.event = event;
    if (
      !drag.started &&
      Math.hypot(
        event.clientX - drag.screen.x,
        event.clientY - drag.screen.y,
      ) >= 5
    ) {
      drag.started = true;
      stopHoverPreview();
      overlay = el("div", "material-selection-box");
      overlay.setAttribute("aria-hidden", "true");
      document.body.append(overlay);
      document.body.classList.add("material-selecting");
      frame = requestAnimationFrame(autoScroll);
    }
    if (drag.started) {
      event.preventDefault();
      update();
    }
  }
  async function up(event) {
    if (!drag || event.pointerId !== drag.pointerId) return;
    if (drag.started) {
      drag.event = event;
      update();
      const { hit, base } = drag;
      removeDrag();
      if (hit.overflow) {
        render();
        toast("单次最多选择 5000 个素材，请缩小选择范围。");
        return;
      }
      if (await commit(hit.indices, base))
        anchor = selection.size
          ? {
              key: Catalog.key,
              index: Catalog.get(state.selected)?.__catalogIndex,
            }
          : null;
    } else {
      const base = drag.base;
      removeDrag();
      selection.clear();
      for (const id of base) selection.add(id);
      state.selected = [...base].at(-1) ?? null;
      anchor = null;
      render();
      inspect(state.selected ? Catalog.get(state.selected) : null);
      selectionStatus();
    }
  }
  function setup() {
    if (initialized) return;
    initialized = true;
    const gallery = $("#gallery");
    gallery.addEventListener(
      "scroll",
      () => {
        if (drag?.started) update();
      },
      { passive: true },
    );
    gallery.addEventListener("pointerdown", down);
    gallery.addEventListener("pointermove", move);
    gallery.addEventListener("pointerup", up);
    gallery.addEventListener("pointercancel", () => {
      cancel();
      render();
    });
    window.addEventListener("blur", () => {
      if (drag) {
        cancel();
        render();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && (drag || pending)) {
        cancel();
        render();
      }
    });
  }
  return {
    setup,
    click,
    cancel,
    render,
    get busy() {
      return pending;
    },
  };
})();
