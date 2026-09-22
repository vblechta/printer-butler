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
        <div><dt>Pages</dt><dd>${formatNumber(printer.page_count)}</dd></div>
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
  return supplies.filter((supply) => {
    if (["toner", "ink", "photoconductor"].includes(supply.kind)) return true;
    if (/drum/i.test(supply.name || "")) return true;
    if (supply.kind === "waste" && typeof supply.percent === "number" && supply.percent >= 0) return true;
    return typeof supply.percent === "number" && supply.percent >= 0 && supply.percent <= 40;
  });
}

function supplyRow(supply) {
  const percent = typeof supply.percent === "number" && supply.percent >= 0 ? supply.percent : null;
  const width = percent == null ? 100 : percent;
  const cls = percent == null ? "unknown" : supply.color || "other";
  return `
    <div class="bar-row">
      <span>${escapeHtml(supply.name)}</span>
      <div class="track"><div class="fill ${cls}" style="width:${width}%"></div></div>
      <span>${percent == null ? "n/a" : percent + "%"}</span>
    </div>
  `;
}

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) node.textContent = String(value);
}

function formatNumber(value) {
  if (value == null || value === "") return "—";
  return Number(value).toLocaleString("en-US");
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
