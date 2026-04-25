(function () {
  "use strict";

  var bootstrapEl = document.getElementById("composer-bootstrap");
  var panel = document.getElementById("composer-panel");
  if (!bootstrapEl || !panel) return;

  var bootstrap = JSON.parse(bootstrapEl.textContent || "{}");

  var SECTION_TYPES = {
    text:      { label: "Text",      hint: "Heading or message · Jinja-aware" },
    logo:      { label: "Logo",      hint: "Brand graphic, scalable" },
    separator: { label: "Separator", hint: "Thin horizontal divider" },
    tasks:     { label: "Tasks",     hint: "Worker's task list" },
    blank:     { label: "Blank",     hint: "Vertical spacer line" },
  };
  var PALETTE_ORDER = ["text", "logo", "separator", "tasks", "blank"];

  var ICONS = {
    text:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7V5h16v2"/><path d="M9 19h6"/><path d="M12 5v14"/></svg>',
    logo:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>',
    separator: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 12h18"/></svg>',
    tasks:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="6" height="6" rx="1"/><rect x="3" y="14" width="6" height="6" rx="1"/><path d="M12 7h9M12 17h9"/><path d="M5 6.5l1 1 2-2"/></svg>',
    blank:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="3 3"><rect x="4" y="4" width="16" height="16" rx="2"/></svg>',
  };

  var BASE = {
    type: null, value: null, align: "left", font: "a",
    width: 1, height: 1, bold: false, underline: 0,
    scale: 1.0, trailing_blank: true,
  };
  var TYPE_DEFAULTS = {
    text:      { type: "text",      value: "Sample text", align: "left",   trailing_blank: true },
    logo:      { type: "logo",      value: null,          align: "center", scale: 1.0, trailing_blank: true },
    separator: { type: "separator", value: null,          align: "center", trailing_blank: true },
    tasks:     { type: "tasks",     value: null,          align: "left",   trailing_blank: true },
    blank:     { type: "blank",     value: null,          align: "left",   trailing_blank: false },
  };

  var palette  = document.getElementById("composer-palette");
  var dropzone = document.getElementById("composer-dropzone");
  var statusEl = document.getElementById("composer-status");
  var countEl  = document.getElementById("composer-count");
  var dirtyEl  = document.getElementById("composer-dirty");
  var previewBtn = document.getElementById("composer-preview");
  var saveBtn    = document.getElementById("composer-save");
  var resetBtn   = document.getElementById("composer-reset");
  var previewImg = document.querySelector(".receipt__image");
  var receiptWrap = document.querySelector(".receipt");

  var sections = normalizeAll(clone(bootstrap.current && bootstrap.current.sections));
  var savedHash = hash(sections);
  var defaults  = normalizeAll(clone(bootstrap["default"] && bootstrap["default"].sections));

  var dragSourceIndex = null;
  var dragSourceKind  = null;
  var dropTargetIndex = null;
  var pendingPreviewToken = 0;

  function clone(value) { return JSON.parse(JSON.stringify(value || [])); }

  function normalize(section) {
    var out = Object.assign({}, BASE, section);
    if (out.value === undefined) out.value = null;
    if (out.font !== "b") out.font = "a";
    if (["left", "center", "right"].indexOf(out.align) === -1) out.align = "left";
    out.width  = clamp(parseInt(out.width,  10) || 1, 1, 8);
    out.height = clamp(parseInt(out.height, 10) || 1, 1, 8);
    out.bold = !!out.bold;
    out.underline = clamp(parseInt(out.underline, 10) || 0, 0, 2);
    out.scale = parseFloat(out.scale);
    if (!isFinite(out.scale) || out.scale <= 0) out.scale = 1.0;
    out.trailing_blank = !!out.trailing_blank;
    return out;
  }
  function normalizeAll(arr) { return (arr || []).map(normalize); }

  function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, n)); }

  function hash(value) {
    return JSON.stringify(value);
  }

  function isDirty() { return hash(sections) !== savedHash; }

  function setStatus(message, kind) {
    statusEl.textContent = message;
    statusEl.classList.remove("is-error", "is-ok", "is-busy");
    if (kind) statusEl.classList.add("is-" + kind);
  }

  function setDirtyChip() {
    var chip = dirtyEl.parentElement;
    if (isDirty()) {
      dirtyEl.textContent = "unsaved changes";
      chip.classList.remove("chip--moss");
      chip.classList.add("chip--sand");
      chip.querySelector(".dot").className = "dot dot--sand";
    } else {
      dirtyEl.textContent = "in sync with config";
      chip.classList.remove("chip--sand");
      chip.classList.add("chip--moss");
      chip.querySelector(".dot").className = "dot dot--moss";
    }
  }

  function updateCount() {
    var n = sections.length;
    countEl.textContent = n + " block" + (n === 1 ? "" : "s");
  }

  // ── Palette ────────────────────────────────────────────────
  function renderPalette() {
    palette.innerHTML = "";
    PALETTE_ORDER.forEach(function (kind) {
      var meta = SECTION_TYPES[kind];
      var li = document.createElement("li");

      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "palette__item palette__item--" + kind;
      btn.draggable = true;
      btn.dataset.kind = kind;
      btn.innerHTML =
        '<span class="palette__icon">' + ICONS[kind] + '</span>' +
        '<span class="palette__label">' + meta.label + '</span>' +
        '<span class="palette__hint">' + meta.hint + '</span>';

      btn.addEventListener("click", function () {
        appendBlock(kind);
        setStatus("Added " + meta.label.toLowerCase() + " block at the bottom.");
      });
      btn.addEventListener("dragstart", function (e) {
        dragSourceKind = kind;
        dragSourceIndex = null;
        btn.classList.add("is-dragging");
        try { e.dataTransfer.setData("text/plain", "palette:" + kind); } catch (_) {}
        e.dataTransfer.effectAllowed = "copy";
      });
      btn.addEventListener("dragend", function () {
        btn.classList.remove("is-dragging");
        dragSourceKind = null;
        clearDropMarker();
      });
      li.appendChild(btn);
      palette.appendChild(li);
    });
  }

  // ── Drop zone ──────────────────────────────────────────────
  function appendBlock(kind) {
    var section = normalize(Object.assign({}, TYPE_DEFAULTS[kind] || { type: kind }));
    sections.push(section);
    renderDropzone();
    setDirtyChip();
  }

  function removeBlock(index) {
    sections.splice(index, 1);
    renderDropzone();
    setDirtyChip();
  }

  function moveBlock(fromIndex, toIndex) {
    if (fromIndex === toIndex) return;
    var item = sections.splice(fromIndex, 1)[0];
    var insertAt = toIndex > fromIndex ? toIndex - 1 : toIndex;
    sections.splice(insertAt, 0, item);
    renderDropzone();
    setDirtyChip();
  }

  function insertBlock(kind, atIndex) {
    var section = normalize(Object.assign({}, TYPE_DEFAULTS[kind] || { type: kind }));
    sections.splice(atIndex, 0, section);
    renderDropzone();
    setDirtyChip();
  }

  function patchBlock(index, patch) {
    sections[index] = normalize(Object.assign({}, sections[index], patch));
    renderDropzone();
    setDirtyChip();
  }

  function renderDropzone() {
    dropzone.innerHTML = "";
    updateCount();

    if (sections.length === 0) {
      var empty = document.createElement("div");
      empty.className = "dropzone__empty";
      empty.innerHTML =
        "<strong>Empty composing stick</strong>" +
        "<span>Drag a block from the typecase, or tap one to drop it here.</span>";
      dropzone.appendChild(empty);
      return;
    }

    sections.forEach(function (section, index) {
      dropzone.appendChild(buildBlock(section, index));
    });
  }

  function buildBlock(section, index) {
    var li = document.createElement("li");
    li.className = "block block--" + section.type;
    if (section.bold) li.classList.add("has-bold");
    if (section.underline) li.classList.add("has-underline");
    if (section.font === "b") li.classList.add("is-fontb");
    if (section.height >= 2 || section.width >= 2) li.classList.add("is-double");
    li.draggable = true;
    li.dataset.index = String(index);

    li.addEventListener("dragstart", function (e) {
      dragSourceIndex = index;
      dragSourceKind = null;
      li.classList.add("is-dragging");
      try { e.dataTransfer.setData("text/plain", "block:" + index); } catch (_) {}
      e.dataTransfer.effectAllowed = "move";
    });
    li.addEventListener("dragend", function () {
      li.classList.remove("is-dragging");
      dragSourceIndex = null;
      clearDropMarker();
    });

    var handle = document.createElement("span");
    handle.className = "block__handle";
    handle.title = "Drag to reorder";
    handle.setAttribute("aria-hidden", "true");
    handle.textContent = "⋮⋮";
    li.appendChild(handle);

    li.appendChild(buildBody(section, index));
    li.appendChild(buildDock(section, index));
    return li;
  }

  function buildBody(section, index) {
    var body = document.createElement("div");
    body.className = "block__body";

    var cell = document.createElement("div");
    if (section.type === "text") {
      cell.className = "block__cell block__cell--span block__cell--" + section.align;
    } else {
      cell.className = "block__cell block__cell--" + section.align;
    }

    var icon = document.createElement("span");
    icon.className = "block__icon block__icon--" + section.type;
    icon.setAttribute("aria-hidden", "true");
    icon.innerHTML = ICONS[section.type] || "";
    cell.appendChild(icon);

    cell.appendChild(buildContent(section, index));
    body.appendChild(cell);
    return body;
  }

  function buildContent(section, index) {
    if (section.type === "text") {
      var pill = document.createElement("label");
      pill.className = "block__pill block__pill--input";
      var input = document.createElement("input");
      input.type = "text";
      input.value = section.value || "";
      input.placeholder = "type or paste text…";
      input.spellcheck = false;
      input.style.textAlign = section.align;
      input.addEventListener("input", function () {
        sections[index].value = input.value;
        setDirtyChip();
      });
      input.addEventListener("focus", function () {
        var li = input.closest(".block");
        if (li) li.draggable = false;
      });
      input.addEventListener("blur", function () {
        var li = input.closest(".block");
        if (li) li.draggable = true;
      });
      pill.appendChild(input);
      return pill;
    }

    if (section.type === "logo") {
      var p = document.createElement("span");
      p.className = "block__pill block__pill--logo";
      var pct = Math.round((section.scale || 1) * 100);
      p.textContent = "crew.day · " + pct + "%";
      return p;
    }

    if (section.type === "separator") {
      var span = document.createElement("span");
      span.className = "block__pill block__pill--separator";
      span.innerHTML = '<i class="block__rule-line"></i> separator <i class="block__rule-line"></i>';
      return span;
    }

    if (section.type === "tasks") {
      var t = document.createElement("span");
      t.className = "block__pill block__pill--tasks";
      t.textContent = "↳ task list";
      return t;
    }

    var b = document.createElement("span");
    b.className = "block__pill block__pill--blank";
    b.textContent = "(blank line)";
    return b;
  }

  function buildDock(section, index) {
    var dock = document.createElement("div");
    dock.className = "block__dock";

    dock.appendChild(buildAlignDock(section, index));

    if (section.type === "text") {
      dock.appendChild(buildFontDock(section, index));
      dock.appendChild(buildSizeDock(section, index));
      dock.appendChild(modBtn("B", section.bold, function () {
        patchBlock(index, { bold: !section.bold });
      }, "Toggle bold"));
      dock.appendChild(modBtn("U", section.underline > 0, function () {
        patchBlock(index, { underline: section.underline > 0 ? 0 : 1 });
      }, "Toggle underline"));
    }

    if (section.type === "logo") {
      dock.appendChild(buildLogoScaleDock(section, index));
    }

    if (section.type === "separator") {
      dock.appendChild(modBtn("blank↓", section.trailing_blank, function () {
        patchBlock(index, { trailing_blank: !section.trailing_blank });
      }, "Toggle trailing blank line", "ghost"));
    }

    var remove = document.createElement("button");
    remove.type = "button";
    remove.className = "mod mod--remove";
    remove.title = "Remove block";
    remove.innerHTML = "✕";
    remove.addEventListener("click", function () { removeBlock(index); });
    dock.appendChild(remove);

    return dock;
  }

  function modBtn(label, active, onClick, title, variant) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "mod" + (variant ? " mod--" + variant : "") + (active ? " is-active" : "");
    b.textContent = label;
    if (title) b.title = title;
    b.addEventListener("click", onClick);
    return b;
  }

  var ALIGN_ICONS = {
    left:   '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="21" x2="3" y1="6" y2="6"/><line x1="15" x2="3" y1="12" y2="12"/><line x1="17" x2="3" y1="18" y2="18"/></svg>',
    center: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="21" x2="3" y1="6" y2="6"/><line x1="17" x2="7" y1="12" y2="12"/><line x1="19" x2="5" y1="18" y2="18"/></svg>',
    right:  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="21" x2="3" y1="6" y2="6"/><line x1="21" x2="9" y1="12" y2="12"/><line x1="21" x2="7" y1="18" y2="18"/></svg>',
  };

  function buildAlignDock(section, index) {
    var group = document.createElement("div");
    group.className = "mod-group";
    ["left", "center", "right"].forEach(function (align) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mod" + (section.align === align ? " is-active" : "");
      b.title = "Align " + align;
      b.innerHTML = ALIGN_ICONS[align];
      b.addEventListener("click", function () { patchBlock(index, { align: align }); });
      group.appendChild(b);
    });
    return group;
  }

  function buildFontDock(section, index) {
    var group = document.createElement("div");
    group.className = "mod-group";
    [
      { label: "A", font: "a", title: "Font A (standard)" },
      { label: "B", font: "b", title: "Font B (compact)" },
    ].forEach(function (opt) {
      var active = section.font === opt.font;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mod" + (active ? " is-active" : "");
      b.title = opt.title;
      b.textContent = opt.label;
      b.addEventListener("click", function () { patchBlock(index, { font: opt.font }); });
      group.appendChild(b);
    });
    return group;
  }

  function buildSizeDock(section, index) {
    var group = document.createElement("div");
    group.className = "mod-group";
    [
      { label: "1×", width: 1, height: 1, title: "Normal size" },
      { label: "2×", width: 2, height: 2, title: "Double size" },
    ].forEach(function (opt) {
      var active = section.width === opt.width && section.height === opt.height;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mod" + (active ? " is-active" : "");
      b.title = opt.title;
      b.textContent = opt.label;
      b.addEventListener("click", function () {
        patchBlock(index, { width: opt.width, height: opt.height });
      });
      group.appendChild(b);
    });
    return group;
  }

  function buildLogoScaleDock(section, index) {
    var group = document.createElement("div");
    group.className = "mod-group";
    [
      { label: "¼", scale: 0.25 },
      { label: "½", scale: 0.5  },
      { label: "¾", scale: 0.75 },
      { label: "1×", scale: 1.0 },
    ].forEach(function (opt) {
      var active = Math.abs((section.scale || 1) - opt.scale) < 0.01;
      var b = document.createElement("button");
      b.type = "button";
      b.className = "mod" + (active ? " is-active" : "");
      b.title = "Logo scale " + opt.label;
      b.textContent = opt.label;
      b.addEventListener("click", function () { patchBlock(index, { scale: opt.scale }); });
      group.appendChild(b);
    });
    return group;
  }

  // ── Drag-over targeting ────────────────────────────────────
  function clearDropMarker() {
    var marker = dropzone.querySelector(".drop-marker");
    if (marker) marker.remove();
    dropzone.classList.remove("is-drag-over");
  }

  function targetIndexFromY(clientY) {
    var children = dropzone.querySelectorAll(".block");
    for (var i = 0; i < children.length; i++) {
      var rect = children[i].getBoundingClientRect();
      if (clientY < rect.top + rect.height / 2) return i;
    }
    return children.length;
  }

  function showDropMarker(beforeIndex) {
    clearDropMarker();
    dropzone.classList.add("is-drag-over");
    var marker = document.createElement("div");
    marker.className = "drop-marker";
    var children = dropzone.querySelectorAll(".block");
    if (beforeIndex >= children.length) {
      dropzone.appendChild(marker);
    } else {
      dropzone.insertBefore(marker, children[beforeIndex]);
    }
  }

  dropzone.addEventListener("dragover", function (e) {
    if (dragSourceKind === null && dragSourceIndex === null) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = dragSourceKind ? "copy" : "move";
    dropTargetIndex = targetIndexFromY(e.clientY);
    showDropMarker(dropTargetIndex);
  });

  dropzone.addEventListener("dragleave", function (e) {
    if (e.target === dropzone) clearDropMarker();
  });

  dropzone.addEventListener("drop", function (e) {
    e.preventDefault();
    var atIndex = dropTargetIndex == null ? sections.length : dropTargetIndex;
    if (dragSourceKind) {
      insertBlock(dragSourceKind, atIndex);
      setStatus("Inserted " + (SECTION_TYPES[dragSourceKind].label.toLowerCase()) + " block.");
    } else if (dragSourceIndex != null) {
      moveBlock(dragSourceIndex, atIndex);
      setStatus("Reordered blocks.");
    }
    clearDropMarker();
    dragSourceKind = null;
    dragSourceIndex = null;
    dropTargetIndex = null;
  });

  // ── Preview / save / reset ─────────────────────────────────
  function postJSON(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "same-origin",
    });
  }

  function generatePreview() {
    var token = ++pendingPreviewToken;
    setStatus("Rendering preview…", "busy");
    previewBtn.disabled = true;
    postJSON("/api/template/preview", { sections: sections })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || "Preview failed"); });
        return r.json();
      })
      .then(function (data) {
        if (token !== pendingPreviewToken) return;
        if (previewImg && data.src) {
          previewImg.src = data.src;
          previewImg.width = data.width_dots;
          previewImg.height = data.height_dots;
          if (receiptWrap) {
            receiptWrap.style.setProperty("--receipt-width-dots", data.width_dots + "px");
          }
        }
        setStatus("Preview rendered. Looks good? Save when ready.", "ok");
      })
      .catch(function (err) {
        if (token !== pendingPreviewToken) return;
        setStatus("Preview failed · " + err.message, "error");
      })
      .finally(function () {
        if (token === pendingPreviewToken) previewBtn.disabled = false;
      });
  }

  function saveTemplate() {
    setStatus("Saving template…", "busy");
    saveBtn.disabled = true;
    postJSON("/api/template/save", { sections: sections })
      .then(function (r) {
        if (!r.ok) return r.json().then(function (j) { throw new Error(j.detail || "Save failed"); });
        return r.json();
      })
      .then(function () {
        savedHash = hash(sections);
        setDirtyChip();
        setStatus("Template saved to YAML config.", "ok");
        generatePreview();
      })
      .catch(function (err) {
        setStatus("Save failed · " + err.message, "error");
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  function resetToDefault() {
    sections = normalizeAll(clone(defaults));
    renderDropzone();
    setDirtyChip();
    setStatus("Loaded bundled default. Preview or save to apply.", "ok");
  }

  previewBtn.addEventListener("click", generatePreview);
  saveBtn.addEventListener("click", saveTemplate);
  resetBtn.addEventListener("click", resetToDefault);

  renderPalette();
  renderDropzone();
  setDirtyChip();
  setStatus("Loaded current template from YAML config.");
})();
