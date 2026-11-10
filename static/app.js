const grid = document.getElementById("grid");
const empty = document.getElementById("empty");
const filterInput = document.getElementById("filter");
const livePill = document.getElementById("live-pill");
const updated = document.getElementById("updated");
const healthFilters = document.getElementById("health-filters");
const versionLabel = document.getElementById("app-version");

let snapshot = JSON.parse(document.getElementById("bootstrap").textContent);
let healthFilter = "all";
let autoscaleFrame = 0;

function render() {
  const query = filterInput.value.trim().toLowerCase();
  const printers = (snapshot.printers || []).filter((printer) => {
    if (healthFilter !== "all" && printer.health !== healthFilter) return false;
    if (!query) return true;
    const hay = [printer.name, printer.ip, printer.location, printer.brand, printer.model, printer.status]
      .join(" ")
      .toLowerCase();
    return hay.includes(query);
  });
  const summary = snapshot.summary || {};
  setText("sum-total", summary.total ?? printers.length);
  setText("sum-ok", summary.ok ?? 0);
  setText("sum-warning", summary.warning ?? 0);
  setText("sum-error", summary.error ?? 0);
  setText("sum-offline", summary.offline ?? 0);
  grid.innerHTML = printers.map(cardHtml).join("");
  empty.classList.toggle("hidden", printers.length > 0);
  scheduleAutoscale();
}

function cardHtml(printer) {
    const supplies = visibleSupplies(printer.supplies || [])
      .map(supplyRow)
      .join("") || `<div class="muted">No supply data</div>`;
    const trays = (printer.trays || [])
      .filter((tray) => !/bypass|manual/i.test(tray.name || ""))
      .map((tray) => {
        const level = tray.state === "empty" ? "empty" : formatPercent(tray.percent) || tray.state || "";
        return `<span class="tray">${escapeHtml(tray.name)}${tray.media ? ` · ${escapeHtml(tray.media)}` : ""}${level ? ` · ${level}` : ""}</span>`;
      })
      .join("");
  const alerts = (printer.alerts || []).map((alert) => escapeHtml(alert)).join(" · ");
  return `
    <article class="card" data-health="${escapeHtml(printer.health)}">
      <div class="card-head">
        <div class="identity">
          <h2>${escapeHtml(printer.name)}</h2>
          <p>${escapeHtml(printer.location || "No location")} · ${escapeHtml(printer.model || "Unknown model")}</p>
        </div>
        <div class="badges">
          ${brandLogo(printer.brand)}
          <span class="badge ${escapeHtml(printer.health)}">${escapeHtml(printer.health)}</span>
        </div>
      </div>
      <dl class="meta">
        <div><dt>Status</dt><dd>${escapeHtml(printer.status || "Unknown")}</dd></div>
        <div class="meta-ip"><dt>IP</dt><dd><a href="${escapeHtml(printer.web_url)}" target="_blank" rel="noreferrer">${escapeHtml(printer.ip)}</a></dd></div>
        <div class="meta-serial"><dt>Serial</dt><dd>${escapeHtml(printer.serial || "—")}</dd></div>
        <div><dt>Pages</dt><dd>${pageCountHtml(printer)}</dd></div>
      </dl>
      <div class="bars">${supplies}</div>
      ${trays ? `<div class="trays">${trays}</div>` : ""}
      ${alerts ? `<p class="alerts">${alerts}</p>` : ""}
      <div class="sources">${escapeHtml((printer.sources || []).join(" · ") || "no source")} · ${formatTime(printer.updated_at)}</div>
    </article>
  `;
}

function brandLogo(brand) {
  const known = { xerox: "xerox", brother: "brother", epson: "epson" };
  const file = known[brand];
  if (!file) {
    return `<span class="badge">${escapeHtml(brand || "unknown")}</span>`;
  }
  return `<img class="brand-logo" src="/static/brands/${file}.svg" alt="${escapeHtml(brand)}" title="${escapeHtml(brand)}">`;
}

function visibleSupplies(supplies) {
  const hideAbove = Number(snapshot.ui && snapshot.ui.hide_supplies_above_percent);
  const threshold = Number.isFinite(hideAbove) ? hideAbove : 100;
  return supplies
    .filter((supply) => {
      const percent = typeof supply.percent === "number" && supply.percent >= 0 ? supply.percent : null;
      const tonerOrDrum =
        ["toner", "ink", "photoconductor"].includes(supply.kind) || /drum/i.test(supply.name || "");
      if (tonerOrDrum) {
        return percent == null || percent <= threshold;
      }
      if (supply.kind === "waste" && percent != null) return true;
      return percent != null && percent <= 40;
    })
    .sort((left, right) => {
      const a = supplySortKey(left);
      const b = supplySortKey(right);
      if (a[0] !== b[0]) return a[0] - b[0];
      if (a[1] !== b[1]) return a[1] - b[1];
      return a[2].localeCompare(b[2]);
    });
}

function isDrumSupply(supply) {
  const name = String(supply.name || "").toLowerCase();
  const kind = String(supply.kind || "").toLowerCase();
  return kind === "photoconductor" || name.includes("drum");
}

function supplySortKey(supply) {
  const name = String(supply.name || "").toLowerCase();
  const kind = String(supply.kind || "").toLowerCase();
  const isDrum = isDrumSupply(supply);
  const isToner = ["toner", "ink"].includes(kind) && !isDrum;
  const colorRank = { black: 0, cyan: 1, magenta: 2, yellow: 3 }[supplyColor(supply)] ?? 4;
  const group = isToner ? 0 : isDrum ? 1 : kind === "waste" ? 2 : 3;
  return [group, colorRank, name];
}

function supplyColor(supply) {
  const blob = `${supply.color || ""} ${supply.name || ""}`.toLowerCase();
  if (/\bcyan\b/.test(blob)) return "cyan";
  if (/\bmagenta\b/.test(blob)) return "magenta";
  if (/\byellow\b/.test(blob)) return "yellow";
  if (/\bblack\b/.test(blob) || /\bbk\b/.test(blob)) return "black";
  const color = String(supply.color || "").toLowerCase();
  if (["black", "cyan", "magenta", "yellow"].includes(color)) return color;
  return "black";
}

function supplyLabel(supply) {
  const name = String(supply.name || "");
  const kind = String(supply.kind || "").toLowerCase();
  const drum = isDrumSupply(supply);
  const toner = ["toner", "ink"].includes(kind) && !drum;
  if (!toner && !drum) return name;
  return name.replace(/\bcartridge\b/gi, " ").replace(/\s+/g, " ").trim();
}

function supplyRow(supply) {
  const percent = typeof supply.percent === "number" && supply.percent >= 0 ? supply.percent : null;
  const width = percent == null ? 100 : percent;
  const color = percent == null ? "unknown" : isDrumSupply(supply) ? supplyColor(supply) : supply.color || "other";
  const cls = [color, percent != null && isDrumSupply(supply) ? "drum" : ""].filter(Boolean).join(" ");
  return `
    <div class="bar-row">
      <span>${escapeHtml(supplyLabel(supply))}</span>
      <div class="track"><div class="fill ${cls}" style="width:${width}%"></div></div>
      <span>${percent == null ? "n/a" : percent + "%"}</span>
    </div>
  `;
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = String(value);
}

function pageCountHtml(printer) {
  const text = formatNumber(printer.page_count);
  if (printer.page_count == null || printer.page_count === "") return text;
  return `<button type="button" class="page-count" data-printer="${escapeHtml(printer.name)}" title="Page statistics">${text}</button>`;
}

function formatNumber(value) {
  if (value == null || value === "") return "—";
  return Number(value).toLocaleString("en-US");
}

function formatPages(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

function formatAverage(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 1 });
}

function formatPercent(value) {
  if (typeof value !== "number" || value < 0) return "";
  return `${value}%`;
}

function formatTime(value) {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function applySnapshot(data) {
  snapshot = data;
  if (data.version) {
    versionLabel.textContent = data.version;
  }
  updated.textContent = `Updated ${formatTime(new Date().toISOString())} · poll every ${data.poll_interval_seconds || 20}s`;
  render();
}

filterInput.addEventListener("input", render);
grid.addEventListener("click", (event) => {
  const button = event.target.closest("button.page-count");
  if (!button) return;
  openPageStats(button.dataset.printer);
});

const pageModal = document.getElementById("page-modal");
const pageChart = document.getElementById("page-chart");
const pageRanges = document.getElementById("page-ranges");
let pageStats = null;
let pageRange = "week";
let pageStatsRequest = 0;

const pageRangeCopy = {
  week: { caption: "Last 7 days", label: "Pages printed each day for the last 7 days" },
  month: { caption: "Last 30 days", label: "Pages printed each day for the last 30 days" },
  year: { caption: "Last 12 months", label: "Pages printed each month for the last 12 months" },
};

function openPageStats(printer) {
  const request = ++pageStatsRequest;
  pageStats = null;
  pageRange = "week";
  setPageRangePressed();
  document.getElementById("page-modal-title").textContent = printer || "Pages";
  document.getElementById("page-modal-count").textContent = "Loading page history…";
  document.getElementById("page-modal-status").textContent = "";
  document.getElementById("page-chart-caption").textContent = "";
  for (const field of ["today", "last_week", "last_month", "average_day", "average_month", "average_year"]) {
    setPageField(field, null, field.startsWith("average"));
  }
  pageChart.className = "page-chart is-empty";
  pageChart.innerHTML = "";
  setPageModalOpen(true);
  loadPageStats(printer, request);
}

async function loadPageStats(printer, request) {
  try {
    const response = await fetch(`/api/printers/${encodeURIComponent(printer)}/pages`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const data = await response.json();
    if (request !== pageStatsRequest) return;
    pageStats = data;
    renderPageStats();
  } catch (err) {
    if (request !== pageStatsRequest) return;
    document.getElementById("page-modal-count").textContent = "";
    document.getElementById("page-modal-status").textContent = "Could not load page history.";
    console.warn(err);
  }
}

function renderPageStats() {
  const stats = pageStats;
  if (!stats) return;
  document.getElementById("page-modal-title").textContent = stats.name || "Pages";
  document.getElementById("page-modal-count").textContent =
    stats.page_count == null ? "Page count unavailable" : `${formatNumber(stats.page_count)} pages`;
  document.getElementById("page-modal-status").textContent = historyNote(stats);
  setPageField("today", stats.today, false);
  setPageField("last_week", stats.last_week, false);
  setPageField("last_month", stats.last_month, false);
  setPageField("average_day", stats.average_day, true);
  setPageField("average_month", stats.average_month, true);
  setPageField("average_year", stats.average_year, true);
  renderPageChart();
}

function historyNote(stats) {
  const every = stats.sample_interval_hours || 6;
  if (!stats.sample_count) {
    return `No readings stored yet. Page count is saved every ${every} hours.`;
  }
  const since = formatHistoryTime(stats.history_since);
  return `Saved every ${every} hours since ${since}. Averages use the print rate since then.`;
}

function formatHistoryTime(value) {
  if (!value) return "the first reading";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setPageField(field, value, average) {
  const node = document.querySelector(`#page-modal [data-field="${field}"]`);
  if (node) node.textContent = average ? formatAverage(value) : formatPages(value);
}

function renderPageChart() {
  const series = (pageStats && pageStats.series && pageStats.series[pageRange]) || [];
  const copy = pageRangeCopy[pageRange];
  const measured = series.some((bar) => typeof bar.pages === "number");
  pageChart.setAttribute("aria-label", copy.label);
  if (!measured) {
    pageChart.className = "page-chart is-empty";
    pageChart.innerHTML = `<p class="muted">Not enough readings yet to draw this chart.</p>`;
    document.getElementById("page-chart-caption").textContent = "";
    return;
  }
  const showValues = series.length <= 12;
  const known = series.filter((bar) => typeof bar.pages === "number");
  const max = Math.max(1, ...known.map((bar) => bar.pages));
  const total = known.reduce((sum, bar) => sum + bar.pages, 0);
  pageChart.className = showValues ? "page-chart" : "page-chart dense";
  pageChart.innerHTML = series
    .map((bar) => {
      const unknown = typeof bar.pages !== "number";
      const pages = unknown ? 0 : bar.pages;
      const height = pages <= 0 ? 0 : Math.max(3, Math.round((pages / max) * 140));
      const value = showValues && pages > 0 ? formatPages(pages) : "";
      const title = unknown ? `${bar.title}: no reading yet` : `${bar.title}: ${formatPages(pages)} pages`;
      return `
        <div class="page-bar${bar.current ? " is-current" : ""}${unknown ? " is-unknown" : ""}" title="${escapeHtml(title)}">
          <span class="page-bar-value">${value}</span>
          <div class="page-bar-track"><div class="page-bar-fill" style="height:${height}px"></div></div>
          <span class="page-bar-label">${escapeHtml(bar.label)}</span>
        </div>
      `;
    })
    .join("");
  document.getElementById("page-chart-caption").textContent = `${copy.caption} · ${formatPages(total)} pages`;
}

function setPageRangePressed() {
  for (const button of pageRanges.querySelectorAll("button[data-range]")) {
    const active = button.dataset.range === pageRange;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  }
}

function setPageModalOpen(open) {
  pageModal.classList.toggle("hidden", !open);
  pageModal.setAttribute("aria-hidden", String(!open));
  if (open) pageModal.querySelector(".modal-card").focus();
}

function closePageStats() {
  pageStatsRequest += 1;
  setPageModalOpen(false);
}

pageRanges.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-range]");
  if (!button || !pageStats) return;
  pageRange = button.dataset.range;
  setPageRangePressed();
  renderPageChart();
});
document.getElementById("page-modal-close").addEventListener("click", closePageStats);
pageModal.addEventListener("click", (event) => {
  if (event.target === pageModal) closePageStats();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !pageModal.classList.contains("hidden")) closePageStats();
});
healthFilters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-health]");
  if (!button) return;
  healthFilter = button.dataset.health;
  for (const node of healthFilters.querySelectorAll("button")) node.classList.toggle("active", node === button);
  render();
});

const fullscreenToggle = document.getElementById("fullscreen-toggle");
const gridStage = document.getElementById("grid-stage");
const kioskFullscreen = queryFlag("fullscreen");
const autoscaleEnabled = queryFlag("autoscale");
let compactMode = kioskFullscreen;

function queryFlag(name) {
  const params = new URLSearchParams(window.location.search);
  if (!params.has(name)) return false;
  const value = params.get(name).trim().toLowerCase();
  return value === "" || ["1", "true", "yes", "on"].includes(value);
}

function syncFullscreenUi() {
  document.documentElement.classList.toggle("is-autoscale", autoscaleEnabled);
  document.body.classList.toggle("is-fullscreen", compactMode);
  document.body.classList.toggle("is-autoscale", autoscaleEnabled);
  fullscreenToggle.setAttribute("aria-pressed", String(compactMode));
  fullscreenToggle.textContent = compactMode ? "Exit fullscreen" : "Fullscreen";
  fullscreenToggle.title = compactMode ? "Exit fullscreen" : "Fullscreen";
  scheduleAutoscale();
}

function scheduleAutoscale() {
  cancelAnimationFrame(autoscaleFrame);
  autoscaleFrame = requestAnimationFrame(applyAutoscale);
}

function applyAutoscale() {
  grid.style.transform = "";
  grid.style.gridTemplateColumns = "";
  grid.style.width = "";
  if (!autoscaleEnabled || !gridStage) return;
  const count = grid.querySelectorAll(".card").length;
  const availW = gridStage.clientWidth;
  const availH = gridStage.clientHeight;
  if (count === 0 || availW < 8 || availH < 8) return;

  let best = null;
  for (let cols = 1; cols <= count; cols += 1) {
    grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    const contentW = Math.max(grid.scrollWidth, 1);
    const contentH = Math.max(grid.scrollHeight, 1);
    const scale = Math.min(availW / contentW, availH / contentH, 1);
    const rows = Math.ceil(count / cols);
    const visualW = availW / cols;
    const visualH = (contentH * scale) / rows;
    const score = Math.min(visualW, visualH);
    if (!best || score > best.score) {
      best = { cols, scale, score };
    }
  }
  grid.style.gridTemplateColumns = `repeat(${best.cols}, minmax(0, 1fr))`;
  if (best.scale < 0.999) {
    grid.style.width = `${100 / best.scale}%`;
    grid.style.transform = `scale(${best.scale})`;
  }
}

async function enterBrowserFullscreen() {
  if (!document.documentElement.requestFullscreen || document.fullscreenElement) return;
  try {
    await document.documentElement.requestFullscreen();
  } catch {
    /* browsers require a gesture; compact UI still applies */
  }
}

async function toggleFullscreen() {
  compactMode = !compactMode;
  try {
    if (compactMode && document.documentElement.requestFullscreen && !document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    } else if (!compactMode && document.fullscreenElement) {
      await document.exitFullscreen();
    }
  } catch {
    /* CSS compact mode still applies */
  }
  syncFullscreenUi();
}

fullscreenToggle.addEventListener("click", toggleFullscreen);
document.addEventListener("fullscreenchange", () => {
  if (!document.fullscreenElement && compactMode && !kioskFullscreen) {
    compactMode = false;
    syncFullscreenUi();
  }
});

syncFullscreenUi();
if (kioskFullscreen) {
  enterBrowserFullscreen();
  document.addEventListener("pointerdown", enterBrowserFullscreen, { once: true });
}

window.addEventListener("resize", scheduleAutoscale);
window.addEventListener("orientationchange", scheduleAutoscale);
grid.addEventListener("load", scheduleAutoscale, true);
if (window.ResizeObserver && gridStage) {
  new ResizeObserver(scheduleAutoscale).observe(gridStage);
}
applySnapshot(snapshot);

if (window.EventSource) {
  const source = new EventSource("/api/stream");
  source.onopen = () => {
    livePill.textContent = "Live";
    livePill.className = "pill live";
  };
  source.onmessage = (event) => {
    try {
      applySnapshot(JSON.parse(event.data));
    } catch (err) {
      console.warn("Bad live payload", err);
    }
  };
  source.onerror = () => {
    livePill.textContent = "Reconnecting";
    livePill.className = "pill connecting";
  };
} else {
  livePill.textContent = "Polling";
  livePill.className = "pill connecting";
  setInterval(async () => {
    const response = await fetch("/api/printers");
    applySnapshot(await response.json());
  }, 5000);
}
