/* ==========================================================================
   Data Cleaner — frontend logic.
   ========================================================================== */

let selectedFile = null;
let currentSummary = [];
let selectedColumnName = null;

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request to ${path} failed (${res.status})`);
  return data;
}

function showError(message) {
  const banner = document.getElementById("error-banner");
  document.getElementById("error-banner-text").textContent = message;
  banner.classList.remove("hidden");
  banner.scrollIntoView({ behavior: "smooth", block: "nearest" });
}
document.getElementById("error-banner-close").addEventListener("click", () => {
  document.getElementById("error-banner").classList.add("hidden");
});

/* ---------- Theme toggle ---------- */
const themeToggleBtn = document.getElementById("theme-toggle");
function applyThemeLabel() {
  const theme = document.documentElement.getAttribute("data-theme");
  themeToggleBtn.textContent = theme === "light" ? "☀ Light" : "🌙 Dark";
}
themeToggleBtn.addEventListener("click", () => {
  const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", next);
  localStorage.setItem("theme", next);
  applyThemeLabel();
});
applyThemeLabel();

/* ---------- Upload flow ---------- */
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const sheetRow = document.getElementById("sheet-row");
const sheetSelect = document.getElementById("sheet-select");
const loadBtn = document.getElementById("load-btn");
const uploadStatus = document.getElementById("upload-status");

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files.length) handleFileChosen(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", (e) => {
  if (e.target.files.length) handleFileChosen(e.target.files[0]);
});

async function handleFileChosen(file) {
  selectedFile = file;
  const ext = file.name.toLowerCase().split(".").pop();
  uploadStatus.textContent = `Selected: ${file.name}`;

  if (ext === "xls" || ext === "xlsx") {
    const formData = new FormData();
    formData.append("file", file);
    try {
      const { sheets } = await api("/sheets", { method: "POST", body: formData });
      sheetSelect.innerHTML = sheets.map((s) => `<option value="${s}">${s}</option>`).join("");
      sheetSelect.classList.remove("hidden");
    } catch (err) {
      showError(err.message);
      return;
    }
  } else {
    sheetSelect.classList.add("hidden");
  }
  sheetRow.classList.remove("hidden");
}

loadBtn.addEventListener("click", async () => {
  if (!selectedFile) return;
  const formData = new FormData();
  formData.append("file", selectedFile);
  const ext = selectedFile.name.toLowerCase().split(".").pop();
  let url = "/upload";
  if (ext === "xls" || ext === "xlsx") url += `?sheet_name=${encodeURIComponent(sheetSelect.value)}`;

  try {
    uploadStatus.textContent = "Loading...";
    const result = await api(url, { method: "POST", body: formData });
    uploadStatus.textContent = `Loaded ${result.filename} (${result.rows} rows x ${result.columns} columns).`;
    document.getElementById("main-panel").classList.remove("hidden");
    await refreshAll();
  } catch (err) {
    uploadStatus.textContent = "";
    showError(err.message);
  }
});

/* ---------- Refresh everything ---------- */
async function refreshAll() {
  const inspect = await api("/inspect");
  currentSummary = inspect.column_summary;
  renderLiveReadout(inspect);
  renderColumnTable(inspect);
  renderColumnSelects(inspect.column_summary);
  await refreshPreview();
  await refreshHistory();
  hideActionPanel();
  hideGenericPreview();
}

function renderLiveReadout(inspect) {
  document.getElementById("live-readout").textContent =
    `R:${inspect.rows.toLocaleString()} · C:${inspect.columns} · dup rows:${inspect.duplicate_rows}`;
}

/* ---------- Column summary table ---------- */
function renderColumnTable(inspect) {
  const body = document.getElementById("column-table-body");
  body.innerHTML = "";
  inspect.column_summary.forEach((col) => {
    const tr = document.createElement("tr");
    tr.className = "col-row";
    tr.dataset.column = col.column;

    const outlierCell =
      col.outlier_count === null ? '<span class="flag-ok">—</span>'
      : col.outlier_count > 0 ? `<span class="flag-warning">⚠ ${col.outlier_count}</span>`
      : '<span class="flag-ok">0</span>';

    const whitespaceCell =
      col.whitespace_count === null ? '<span class="flag-ok">—</span>'
      : col.whitespace_count > 0 ? `<span class="flag-warning">⚠ ${col.whitespace_count}</span>`
      : '<span class="flag-ok">0</span>';

    tr.innerHTML = `
      <td>${col.column}</td>
      <td><span class="badge ${col.type}">${col.type}</span></td>
      <td><span class="missing-bar"><span class="missing-bar-fill" style="width:${col.missing_pct}%"></span></span>${col.missing_count} (${col.missing_pct}%)</td>
      <td>${whitespaceCell}</td>
      <td>${col.unique_count}</td>
      <td>${outlierCell}</td>
      <td><button class="details-toggle-btn" type="button">Details</button></td>
    `;

    tr.addEventListener("click", (e) => {
      if (e.target.closest(".details-toggle-btn")) return;
      selectColumn(col);
    });

    const detailRow = document.createElement("tr");
    detailRow.className = "detail-row hidden";
    const detailCell = document.createElement("td");
    detailCell.colSpan = 7;
    detailRow.appendChild(detailCell);

    tr.querySelector(".details-toggle-btn").addEventListener("click", async () => {
      const isHidden = detailRow.classList.contains("hidden");
      if (isHidden && !detailCell.dataset.loaded) {
        detailCell.innerHTML = '<p class="muted">Loading...</p>';
        detailRow.classList.remove("hidden");
        try {
          const details = await api(`/column-details/${encodeURIComponent(col.column)}`);
          detailCell.innerHTML = renderColumnDetails(col, details);
          detailCell.dataset.loaded = "true";
        } catch (err) {
          detailCell.innerHTML = `<p class="flag-warning">Error: ${err.message}</p>`;
        }
      } else {
        detailRow.classList.toggle("hidden");
      }
    });

    body.appendChild(tr);
    body.appendChild(detailRow);
  });

  highlightSelectedRow();

  document.getElementById("duplicate-rows-note").textContent =
    inspect.duplicate_rows > 0
      ? `${inspect.duplicate_rows} duplicate row(s) detected — see "Whole-dataset actions" below to remove them.`
      : "No duplicate rows detected.";
}

function highlightSelectedRow() {
  document.querySelectorAll("#column-table-body tr.col-row").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.column === selectedColumnName);
  });
}

function renderColumnDetails(col, details) {
  const parts = [];
  parts.push(`<strong>Missing values:</strong> ${col.missing_count} (${col.missing_pct}%). `
    + (details.missing_rows && details.missing_rows.length ? `Example row(s): ${details.missing_rows.join(", ")}` : col.missing_count > 0 ? "" : "None found."));
  if (col.whitespace_count !== null) {
    parts.push(`<strong>Whitespace issues:</strong> ${col.whitespace_count} value(s) have leading/trailing spaces. `
      + (details.whitespace_examples && details.whitespace_examples.length ? `Examples: ${details.whitespace_examples.join(", ")}` : col.whitespace_count > 0 ? "" : "None found."));
  }
  if (col.outlier_count !== null) {
    parts.push(`<strong>Outliers (IQR rule):</strong> ${col.outlier_count} value(s) fall well outside the typical range. `
      + (details.outlier_examples && details.outlier_examples.length ? `Examples: ${details.outlier_examples.join(", ")}` : col.outlier_count > 0 ? "" : "None found."));
  }
  return `<div class="detail-content">${parts.map((p) => `<p>${p}</p>`).join("")}</div>`;
}

function renderColumnSelects(summary) {
  const options = summary.map((c) => `<option value="${c.column}">${c.column}</option>`).join("");
  document.getElementById("filter-column").innerHTML = options;
  document.getElementById("sort-column").innerHTML = options;
}

/* ---------- Column action panel ---------- */
function hideActionPanel() {
  selectedColumnName = null;
  document.getElementById("action-panel-section").classList.add("hidden");
}

function selectColumn(col) {
  selectedColumnName = col.column;
  highlightSelectedRow();

  const section = document.getElementById("action-panel-section");
  section.classList.remove("hidden");
  document.getElementById("action-column-name").textContent = col.column;
  section.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const body = document.getElementById("action-panel-body");
  body.innerHTML = "";

  function group(title, ...controls) {
    const g = document.createElement("div");
    g.className = "action-group";
    const h = document.createElement("h3");
    h.textContent = title;
    g.appendChild(h);
    controls.forEach((c) => g.appendChild(c));
    body.appendChild(g);
  }

  if (col.type === "Integer" || col.type === "Float") {
    group("Missing values", buildFillControls(col, ["mean", "median", "zero", "ffill", "bfill", "custom"]), buildDropMissingControl(col));
    if (col.outlier_count > 0) {
      const g = document.createElement("div");
      g.className = "action-group warning";
      const h = document.createElement("h3");
      h.textContent = `⚠ Outliers detected (${col.outlier_count})`;
      g.appendChild(h);
      g.appendChild(buildOutlierControl(col));
      body.appendChild(g);
    }
    group("Convert type", buildConvertControl(col));
  } else if (col.type === "Datetime") {
    group("Missing values", buildFillControls(col, ["ffill", "bfill", "custom"]), buildDropMissingControl(col));
    group("Convert type", buildConvertControl(col));
  } else {
    group("Missing values", buildFillControls(col, ["mode", "ffill", "bfill", "custom"]), buildDropMissingControl(col));
    group("Text cleanup", buildWhitespaceControl(col), buildCaseControl(col));
    group("Convert type", buildConvertControl(col));
  }

  group("Column", buildRenameControl(col), buildRemoveColumnControl(col));
}

function makeRow(...children) {
  const row = document.createElement("div");
  row.className = "action-row";
  children.forEach((c) => row.appendChild(c));
  return row;
}
function makeLabel(text) {
  const l = document.createElement("label");
  l.textContent = text;
  return l;
}

function buildFillControls(col, methods) {
  const wrap = document.createElement("div");
  const methodSelect = document.createElement("select");
  methodSelect.innerHTML = methods.map((m) => `<option value="${m}">${m}</option>`).join("");
  const customInput = document.createElement("input");
  customInput.type = "text";
  customInput.placeholder = "custom value";
  customInput.classList.add("hidden");
  methodSelect.addEventListener("change", () => customInput.classList.toggle("hidden", methodSelect.value !== "custom"));
  const previewBtn = document.createElement("button");
  previewBtn.textContent = "Preview fill";
  previewBtn.addEventListener("click", () => {
    runColumnOperation("fill_missing", { column: col.column, method: methodSelect.value, custom_value: customInput.value }, wrap);
  });
  wrap.appendChild(makeRow(makeLabel("Fill missing with"), methodSelect, customInput, previewBtn));
  return wrap;
}

function buildDropMissingControl(col) {
  const wrap = document.createElement("div");
  const btn = document.createElement("button");
  btn.textContent = "Preview: drop rows missing this column";
  btn.addEventListener("click", () => runColumnOperation("drop_missing_rows", { columns: [col.column] }, wrap));
  wrap.appendChild(makeRow(btn));
  return wrap;
}

function buildWhitespaceControl(col) {
  const wrap = document.createElement("div");
  const btn = document.createElement("button");
  btn.textContent = "Preview: trim whitespace";
  btn.addEventListener("click", () => runColumnOperation("strip_whitespace", { columns: [col.column] }, wrap));
  wrap.appendChild(makeRow(btn));
  return wrap;
}

function buildCaseControl(col) {
  const wrap = document.createElement("div");
  const select = document.createElement("select");
  select.innerHTML = `<option value="lower">lowercase</option><option value="upper">UPPERCASE</option><option value="title">Title Case</option>`;
  const btn = document.createElement("button");
  btn.textContent = "Preview";
  btn.addEventListener("click", () => runColumnOperation("standardize_case", { columns: [col.column], case: select.value }, wrap));
  wrap.appendChild(makeRow(makeLabel("Standardize case"), select, btn));
  return wrap;
}

function buildConvertControl(col) {
  const wrap = document.createElement("div");
  const typeSelect = document.createElement("select");
  typeSelect.innerHTML = ["String", "Integer", "Float", "Boolean", "Datetime"].map((t) => `<option value="${t}">${t}</option>`).join("");
  const invalidSelect = document.createElement("select");
  invalidSelect.innerHTML = `<option value="missing">Invalid → missing</option><option value="reject">Reject if invalid</option>`;
  const btn = document.createElement("button");
  btn.textContent = "Preview convert";
  btn.addEventListener("click", () => {
    runColumnOperation("convert_type", { column: col.column, target_type: typeSelect.value, invalid_action: invalidSelect.value }, wrap);
  });
  wrap.appendChild(makeRow(makeLabel("Convert to"), typeSelect, invalidSelect, btn));
  return wrap;
}

function buildOutlierControl(col) {
  const wrap = document.createElement("div");
  const methodSelect = document.createElement("select");
  methodSelect.innerHTML = `<option value="remove">Remove rows</option><option value="mean">Replace with mean</option><option value="custom">Replace with custom value</option>`;
  const customInput = document.createElement("input");
  customInput.type = "text";
  customInput.placeholder = "custom value";
  customInput.classList.add("hidden");
  methodSelect.addEventListener("change", () => customInput.classList.toggle("hidden", methodSelect.value !== "custom"));
  const btn = document.createElement("button");
  btn.className = "danger";
  btn.textContent = `Preview (${col.outlier_count} flagged)`;
  btn.addEventListener("click", () => {
    runColumnOperation("handle_outliers", { column: col.column, method: methodSelect.value, custom_value: customInput.value }, wrap);
  });
  wrap.appendChild(makeRow(makeLabel("Handle outliers"), methodSelect, customInput, btn));
  return wrap;
}

function buildRenameControl(col) {
  const wrap = document.createElement("div");
  const input = document.createElement("input");
  input.type = "text";
  input.placeholder = "new column name";
  input.value = col.column;
  const btn = document.createElement("button");
  btn.textContent = "Preview rename";
  btn.addEventListener("click", () => runColumnOperation("rename_column", { old_name: col.column, new_name: input.value }, wrap));
  wrap.appendChild(makeRow(makeLabel("Rename column to"), input, btn));
  return wrap;
}

function buildRemoveColumnControl(col) {
  const wrap = document.createElement("div");
  const btn = document.createElement("button");
  btn.className = "danger";
  btn.textContent = `Preview: remove column "${col.column}"`;
  btn.addEventListener("click", () => runColumnOperation("remove_columns", { columns: [col.column] }, wrap));
  wrap.appendChild(makeRow(btn));
  return wrap;
}

/* ---------- Preview / apply for a single column operation ---------- */
async function runColumnOperation(operation, params, containerEl) {
  const old = containerEl.querySelector(".inline-preview");
  if (old) old.remove();
  try {
    const result = await api("/clean", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ operation, params, apply: false }),
    });
    containerEl.appendChild(buildInlinePreview(result, operation, params));
  } catch (err) {
    const errEl = document.createElement("p");
    errEl.className = "inline-preview flag-warning";
    errEl.textContent = `Error: ${err.message}`;
    containerEl.appendChild(errEl);
  }
}

function buildInlinePreview(result, operation, params) {
  const box = document.createElement("div");
  box.className = "action-panel inline-preview";
  box.style.marginTop = "8px";

  const summary = document.createElement("p");
  summary.className = "muted";
  summary.textContent = `Rows: ${result.rows_before} → ${result.rows_after}. ${JSON.stringify(result.info)}`;
  box.appendChild(summary);
  box.appendChild(buildPreviewTable(result.preview));

  const applyBtn = document.createElement("button");
  applyBtn.className = "success";
  applyBtn.textContent = "Apply";
  applyBtn.addEventListener("click", async () => {
    await api("/clean", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, params, apply: true }) });
    await refreshAll();
  });
  const discardBtn = document.createElement("button");
  discardBtn.textContent = "Discard";
  discardBtn.addEventListener("click", () => box.remove());

  box.appendChild(makeRow(applyBtn, discardBtn));
  return box;
}

function buildPreviewTable(rows) {
  const wrap = document.createElement("div");
  wrap.className = "table-scroll";
  const table = document.createElement("table");
  if (rows.length) {
    const cols = Object.keys(rows[0]);
    table.innerHTML = `<thead><tr>${cols.map((c) => `<th>${c}</th>`).join("")}</tr></thead>` +
      `<tbody>${rows.map((r) => `<tr>${cols.map((c) => `<td>${r[c]}</td>`).join("")}</tr>`).join("")}</tbody>`;
  }
  wrap.appendChild(table);
  return wrap;
}

/* ---------- Whole-dataset actions ---------- */
let pendingWholeOp = null;

function hideGenericPreview() {
  document.getElementById("generic-preview-area").classList.add("hidden");
  pendingWholeOp = null;
}

async function runWholeOperation(operation, params) {
  pendingWholeOp = { operation, params };
  try {
    const result = await api("/clean", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ operation, params, apply: false }) });
    document.getElementById("generic-preview-summary").textContent = `Rows: ${result.rows_before} → ${result.rows_after}. ${JSON.stringify(result.info)}`;
    document.getElementById("generic-preview-table").replaceWith(
      Object.assign(buildPreviewTable(result.preview).querySelector("table"), { id: "generic-preview-table" })
    );
    document.getElementById("generic-preview-area").classList.remove("hidden");
  } catch (err) {
    showError(err.message);
  }
}

document.getElementById("quick-clean-btn").addEventListener("click", () => runWholeOperation("quick_clean", {}));
document.getElementById("dup-preview-btn").addEventListener("click", () => runWholeOperation("remove_duplicates", { keep: document.getElementById("dup-keep").value }));
document.getElementById("fr-preview-btn").addEventListener("click", () => runWholeOperation("find_replace", { find: document.getElementById("fr-find").value, replace: document.getElementById("fr-replace").value }));
document.getElementById("filter-preview-btn").addEventListener("click", () => runWholeOperation("filter_rows", { column: document.getElementById("filter-column").value, operator: document.getElementById("filter-operator").value, value: document.getElementById("filter-value").value }));
document.getElementById("sort-preview-btn").addEventListener("click", () => runWholeOperation("sort", { columns: [document.getElementById("sort-column").value], ascending: document.getElementById("sort-direction").value === "true" }));

document.getElementById("generic-apply-btn").addEventListener("click", async () => {
  if (!pendingWholeOp) return;
  await api("/clean", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...pendingWholeOp, apply: true }) });
  await refreshAll();
});
document.getElementById("generic-discard-btn").addEventListener("click", hideGenericPreview);

/* ---------- Data preview table ---------- */
async function refreshPreview() {
  const n = document.getElementById("preview-rows-select").value;
  const fromEnd = document.getElementById("preview-direction").value === "true";
  const result = await api(`/preview?n=${n}&from_end=${fromEnd}`);
  const table = buildPreviewTable(result.rows).querySelector("table");
  table.id = "preview-table";
  document.getElementById("preview-table").replaceWith(table);
}
document.getElementById("refresh-preview-btn").addEventListener("click", refreshPreview);

/* ---------- History / undo / reset ---------- */
async function refreshHistory() {
  const { steps, at_original } = await api("/history");
  const list = document.getElementById("history-list");
  list.innerHTML = "";

  steps.forEach((label, i) => {
    const li = document.createElement("li");
    li.className = "history-item";

    const labelSpan = document.createElement("span");
    labelSpan.innerHTML = `<span class="step-num">${i}.</span>${label}`;

    const btnRow = document.createElement("span");
    const isCurrent = i === steps.length - 1;
    if (!isCurrent) {
      const previewBtn = document.createElement("button");
      previewBtn.textContent = "Preview";
      previewBtn.addEventListener("click", () => toggleHistoryPreview(i, li));
      const restoreBtn = document.createElement("button");
      restoreBtn.className = "success";
      restoreBtn.textContent = "Restore to here";
      restoreBtn.addEventListener("click", async () => {
        await api(`/history/${i}/restore`, { method: "POST" });
        await refreshAll();
      });
      btnRow.appendChild(previewBtn);
      btnRow.appendChild(restoreBtn);
    } else {
      const tag = document.createElement("span");
      tag.className = "flag-ok";
      tag.textContent = "current";
      btnRow.appendChild(tag);
    }

    li.appendChild(labelSpan);
    li.appendChild(btnRow);

    const previewArea = document.createElement("div");
    previewArea.className = "history-preview hidden";
    li.appendChild(previewArea);
    li._previewArea = previewArea;

    list.appendChild(li);
  });

  document.getElementById("undo-btn").disabled = at_original;
  document.getElementById("reset-btn").disabled = at_original;
}

async function toggleHistoryPreview(index, li) {
  const area = li._previewArea;
  if (!area.classList.contains("hidden")) { area.classList.add("hidden"); return; }
  area.innerHTML = '<p class="muted">Loading...</p>';
  area.classList.remove("hidden");
  try {
    const result = await api(`/history/${index}/preview?n=10`);
    area.innerHTML = "";
    const note = document.createElement("p");
    note.className = "muted";
    note.textContent = `${result.row_count} row(s) at this step. Showing first 10.`;
    area.appendChild(note);
    area.appendChild(buildPreviewTable(result.rows));
  } catch (err) {
    area.innerHTML = `<p class="flag-warning">Error: ${err.message}</p>`;
  }
}

document.getElementById("undo-btn").addEventListener("click", async () => { await api("/undo", { method: "POST" }); await refreshAll(); });
document.getElementById("reset-btn").addEventListener("click", async () => { await api("/reset", { method: "POST" }); await refreshAll(); });

/* ---------- Export ---------- */
document.getElementById("download-btn").addEventListener("click", () => {
  const filename = document.getElementById("export-filename").value || "cleaned_data";
  const format = document.getElementById("export-format").value;
  window.location.href = `/export?format=${format}&filename=${encodeURIComponent(filename)}`;
});