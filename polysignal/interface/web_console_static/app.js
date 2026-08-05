/* PolySignal Research Console - read-only UI. */

let appState = null;
let currentView = "overview";

const $ = (selector) => document.querySelector(selector);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function number(value, digits = 2) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function money(value) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "--";
  const sign = Number(value) < 0 ? "-" : "";
  return `${sign}$${Math.abs(Number(value)).toFixed(2)}`;
}

function percent(value, digits = 1) {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function ratio(value, total) {
  const n = Number(value) || 0;
  const d = Number(total) || 0;
  return d > 0 ? Math.min(100, Math.max(0, (n / d) * 100)) : 0;
}

function statusClass(value) {
  const text = String(value || "").toLowerCase();
  if (text.includes("complete") || text.includes("verified") || text.includes("locked") || text === "closed") return "good";
  if (text.includes("watch") || text.includes("insufficient") || text.includes("pending") || text.includes("unknown")) return "warn";
  if (text.includes("reject") || text.includes("error") || text.includes("missing")) return "bad";
  return "neutral";
}

function tag(value, fallback = "-") {
  const safe = escapeHtml(value || fallback);
  return `<span class="status-tag ${statusClass(value)}">${safe}</span>`;
}

function metric(label, value, foot, tone = "") {
  return `<article class="metric-card"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value ${tone}">${escapeHtml(value)}</div><div class="metric-foot">${foot || ""}</div></article>`;
}

function pageHeader(eyebrow, title, subtitle, runId) {
  return `<div class="page-header"><div><div class="eyebrow">${escapeHtml(eyebrow)}</div><h1 class="page-title">${escapeHtml(title)}</h1><p class="page-subtitle">${escapeHtml(subtitle)}</p></div><div class="page-header-meta"><span class="read-only-tag">READ-ONLY</span><div class="run-id">${escapeHtml(runId || "No run selected")}</div></div></div>`;
}

function notice(kind, title, body, mark = "!") {
  return `<div class="notice ${kind}"><span class="notice-mark">${escapeHtml(mark)}</span><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(body)}</span></div></div>`;
}

function section(title, caption, body, extraClass = "") {
  return `<section class="section ${extraClass}"><div class="section-header"><div><h2 class="section-title">${escapeHtml(title)}</h2>${caption ? `<div class="section-caption">${escapeHtml(caption)}</div>` : ""}</div></div>${body}</section>`;
}

function readinessRow(label, value, total, tone, suffix = "") {
  const safeValue = Number(value) || 0;
  return `<div class="readiness-row"><div class="readiness-meta"><span class="readiness-name">${escapeHtml(label)}</span><span class="readiness-value">${safeValue}${suffix ? ` ${escapeHtml(suffix)}` : ` / ${Number(total) || 0}`}</span></div><div class="bar-track"><div class="bar-fill ${tone || ""}" style="width:${ratio(safeValue, total)}%"></div></div></div>`;
}

function safetyRows(safety) {
  const rows = [
    ["Live trading", !safety.live_trading_enabled, "DISABLED"],
    ["Auto execution", !safety.allow_auto_execution, "LOCKED"],
    ["Paper trading", safety.paper_trading_enabled, safety.paper_trading_enabled ? "ENABLED" : "OFF"],
    ["Authenticated endpoints", !safety.authenticated_endpoints, "NONE"],
    ["Order placement", !safety.order_placement, "BLOCKED"],
    ["Private key handling", !safety.private_key_handling, "NONE"],
  ];
  return `<div class="safety-list">${rows.map(([label, ok, text]) => `<div class="safety-row"><span class="safety-name">${label}</span><span class="safety-state ${ok ? "ok" : "warn"}"><span class="status-dot ${ok ? "green" : "amber"}"></span>${text}</span></div>`).join("")}</div>`;
}

function positionRows(positions, limit = 8) {
  const rows = (positions || []).slice(0, limit);
  if (!rows.length) return `<div class="empty-row">No positions in this snapshot.</div>`;
  return `<div class="table-scroll"><table class="data-table"><thead><tr><th>Market</th><th>Side</th><th>Entry</th><th>Expected edge</th><th>State</th></tr></thead><tbody>${rows.map((row) => `<tr><td><button class="table-link" data-detail-type="position" data-detail-id="${escapeHtml(row.shadow_trade_id)}">${escapeHtml(row.question)}</button><div class="section-caption">${escapeHtml(row.asset)} · ${escapeHtml(row.market_id)}</div></td><td class="${row.side === "YES" ? "side-yes" : "side-no"}">${escapeHtml(row.side)}</td><td class="mono">${row.entry_price === null ? "-" : number(row.entry_price, 3)}</td><td class="mono ${Number(row.expected_edge) > 0 ? "positive" : ""}">${row.expected_edge === null ? "-" : `${(Number(row.expected_edge) * 100).toFixed(2)}%`}</td><td>${tag(row.status)}</td></tr>`).join("")}</tbody></table></div>`;
}

function candidateRows(candidates, limit = 10) {
  const rows = (candidates || []).slice(0, limit);
  if (!rows.length) return `<div class="empty-row">No candidate rows in this snapshot.</div>`;
  return `<div class="table-scroll"><table class="data-table"><thead><tr><th>Asset</th><th>Market</th><th>Side</th><th>Threshold</th><th>Edge</th><th>Decision</th></tr></thead><tbody>${rows.map((row) => `<tr><td><div class="asset-cell"><span class="asset-pill">${escapeHtml(row.asset || "-")}</span><span class="mono">${escapeHtml(row.barrier_direction)}</span></div></td><td><button class="table-link" data-detail-type="candidate" data-detail-id="${escapeHtml(row.market_id)}">${escapeHtml(row.question)}</button><div class="section-caption">${escapeHtml(row.contract_kind)}</div></td><td class="${row.side === "YES" ? "side-yes" : "side-no"}">${escapeHtml(row.side)}</td><td class="mono">${row.threshold_price === null ? "-" : `$${number(row.threshold_price, 2)}`}</td><td class="mono ${Number(row.expected_edge) > 0 ? "positive" : ""}">${row.expected_edge === null ? "-" : `${(Number(row.expected_edge) * 100).toFixed(2)}%`}</td><td>${tag(row.recommended_action)}</td></tr>`).join("")}</tbody></table></div>`;
}

function overview() {
  const c = appState.cohort;
  const r = appState.readiness;
  const safety = appState.system.safety;
  const forwardReady = c.forward_observations > 0 && c.forward_coverage >= 1;
  const statusBody = forwardReady ? "Forward evidence is available for review." : "Forward evidence is not yet mature; PnL remains blank by policy.";
  return `${pageHeader("CONTROL CENTER", "Research control console", "Crypto threshold shadow validation with a clear paper-only operating boundary.", c.run_id)}
    ${notice(forwardReady ? "success" : "warning", forwardReady ? "Forward evidence available" : "Forward horizon pending", statusBody, forwardReady ? "OK" : "!")}
    <div class="metric-grid">
      ${metric("Fresh positions", String(c.positions), `<span class="teal">${c.closed_positions} closed</span>`)}
      ${metric("Forward coverage", percent(c.forward_coverage), `<span class="${c.forward_coverage ? "teal" : "amber"}">${c.forward_observations} qualifying observations</span>`)}
      ${metric("Paper PnL", money(c.pnl), `<span class="${c.pnl === null ? "amber" : "teal"}">${c.pnl === null ? "insufficient data" : "realized"}</span>`, c.pnl === null ? "muted" : "")}
      ${metric("Independent clusters", `${c.cluster_count} / ${c.cluster_target}`, `<span class="${c.cluster_count >= c.cluster_target ? "teal" : "amber"}">${c.cluster_count >= c.cluster_target ? "threshold met" : "research gate pending"}</span>`)}
    </div>
    <div class="two-column">
      ${section("Cohort readiness", "Evidence gates for the current run", `<div class="section-body"><div class="readiness-list">${readinessRow("Historical barrier coverage", r.historical.verified, r.historical.total, "", "verified")}${readinessRow("Forward observations", r.forward.observations, r.forward.positions, "amber")}${readinessRow("Independent clusters", r.clusters.observed, r.clusters.target, "blue")}</div><div class="readiness-note">Historical provenance is complete for ${r.historical.verified} of ${r.historical.total}. The remaining decision gates are forward maturity and independent sample breadth.</div></div>`)}
      ${section("Execution boundary", "Current configuration", `<div class="section-body">${safetyRows(safety)}<div class="safety-note">All controls are display-only. This console cannot place, cancel, sign, or approve orders.</div></div>`)}
    </div>
    ${section("Position queue", "Fresh paper positions from the v7 validator", `<div class="section-body flush">${positionRows(appState.positions)}</div><div class="footer-strip"><span>${c.positions} positions in snapshot</span><button class="button secondary" data-view-jump="cohort" type="button">Open cohort</button></div>`)}
    <div class="two-column bottom-space">${section("Run provenance", "Immutable input and output references", `<div class="section-body">${provenanceList(appState.provenance)}</div>`)}${section("Deterministic paper check", "Fixture verification", `<div class="section-body"><div class="detail-grid">${detailItem("Mode", appState.round_trip.mode)}${detailItem("Gross PnL", money(appState.round_trip.pnl))}${detailItem("Live execution", appState.round_trip.live_execution_allowed ? "Allowed" : "Disabled")}${detailItem("Orders", `${appState.round_trip.orders_recorded} recorded`)}</div></div>`)}</div>`;
}

function detailItem(label, value, className = "") {
  return `<div class="detail-item"><div class="detail-label">${escapeHtml(label)}</div><div class="detail-value ${className}">${escapeHtml(value ?? "-")}</div></div>`;
}

function provenanceList(provenance) {
  const values = [
    ["Candidate CSV", provenance.candidate_file || "-"],
    ["Candidate SHA-256", provenance.candidate_file_sha256 || "-"],
    ["Shadow trades", provenance.shadow_trades_output || "-"],
    ["Output SHA-256", provenance.shadow_trades_output_sha256 || "-"],
  ];
  return `<div class="provenance-list">${values.map(([label, value]) => `<div class="provenance-item"><div class="detail-label">${escapeHtml(label)}</div><div class="detail-value hash">${escapeHtml(value)}</div></div>`).join("")}</div>`;
}

function cohortView() {
  const c = appState.cohort;
  const safety = appState.system.safety;
  return `${pageHeader("COHORT", "Formal v7 cohort", "A run-scoped evidence view for the current crypto threshold experiment.", c.run_id)}
    ${notice("warning", "Research gate active", "The validator keeps PnL null until forward observations satisfy the 240-minute and full-book contract.")}
    <div class="metric-grid">${metric("Markets scanned", String(c.markets_scanned), `${c.crypto_markets} crypto detected`)}${metric("Candidates", String(c.candidates), `${c.shadow_entries} shadow entries`)}${metric("Historical evidence", `${c.historical_verified}/${c.historical_total}`, "verified manifests", "")}${metric("Validation status", c.status.replaceAll("_", " "), c.gamma_exhaustive ? "scan complete" : "scan not exhaustive", "muted")}</div>
    <div class="page-grid">
      ${section("Cohort identity", "Stable run metadata", `<div class="section-body"><div class="detail-grid">${detailItem("Run ID", c.run_id)}${detailItem("Entry minute", c.entry_time)}${detailItem("Discovery schema", c.discovery_schema)}${detailItem("Validator schema", c.validator_schema)}${detailItem("Generated", c.generated_at)}${detailItem("Gamma terminal page", c.gamma_exhaustive ? "No recorded error" : "Recoverable error recorded")}</div></div>`)}
      ${section("Evidence gates", "Current acceptance state", `<div class="section-body"><div class="readiness-list">${readinessRow("Historical barriers", c.historical_verified, c.historical_total, "")}${readinessRow("Forward maturity", c.forward_observations, c.positions, "amber")}${readinessRow("Cluster breadth", c.cluster_count, c.cluster_target, "blue")}</div></div>`)}
    </div>
    <div class="page-grid bottom-space">${section("Positions", "Validator output", `<div class="section-body flush">${positionRows(appState.positions, 30)}</div>`)}${section("Provenance", "Digest references", `<div class="section-body">${provenanceList(appState.provenance)}<div class="safety-note">${safety.live_trading_enabled || safety.allow_auto_execution ? "Unsafe configuration detected." : "Live trading and auto execution are disabled."}</div></div>`)}</div>`;
}

function marketsView() {
  return `${pageHeader("MARKETS", "Candidate monitor", "Filter the discovery snapshot without changing the underlying artifacts.", appState.cohort.run_id)}
    <div class="section table-section"><div class="section-header"><div><h2 class="section-title">Threshold candidates</h2><div class="section-caption">${appState.candidates.length} rows loaded from the run-scoped JSON snapshot</div></div>${tag(appState.cohort.status)}</div><div class="table-toolbar"><input class="input" id="market-search" type="search" placeholder="Search market or asset" aria-label="Search market or asset" /><select class="select" id="market-filter" aria-label="Filter candidate action"><option value="all">All decisions</option><option value="shadow_entry">Shadow entry</option><option value="watch_only">Watch only</option></select><select class="select" id="asset-filter" aria-label="Filter candidate asset"><option value="all">All assets</option><option value="BTC">BTC</option><option value="ETH">ETH</option><option value="SOL">SOL</option></select></div><div id="candidate-table-root" class="section-body flush"></div></div>`;
}

function renderMarketTable() {
  const root = $("#candidate-table-root");
  if (!root) return;
  const query = String($("#market-search")?.value || "").toLowerCase();
  const action = String($("#market-filter")?.value || "all");
  const asset = String($("#asset-filter")?.value || "all");
  const rows = appState.candidates.filter((row) => {
    const matchesQuery = !query || `${row.question} ${row.asset} ${row.market_id}`.toLowerCase().includes(query);
    return matchesQuery && (action === "all" || row.recommended_action === action) && (asset === "all" || row.asset === asset);
  });
  root.innerHTML = candidateRows(rows, 50);
}

function safetyView() {
  const s = appState.system.safety;
  const allLocked = !s.live_trading_enabled && !s.allow_auto_execution && !s.order_placement && !s.private_key_handling;
  return `${pageHeader("RISK & SAFETY", "Execution boundary", "The console exposes evidence and configuration state only; no action route exists.", appState.cohort.run_id)}
    ${notice(allLocked ? "success" : "warning", allLocked ? "Execution surface locked" : "Configuration requires review", allLocked ? "Live trading, auto execution, signing, and order placement are disabled." : "One or more safety flags need operator review.", allLocked ? "OK" : "!")}
    <div class="page-grid">${section("Configuration", "Read from config/risk.yaml and config/llm.yaml", `<div class="section-body">${safetyRows(s)}<div class="detail-grid" style="margin-top:16px">${detailItem("LLM provider", s.llm_provider)}${detailItem("Console mode", appState.system.mode)}${detailItem("Data source", appState.system.data_source)}${detailItem("Network calls", s.network_calls ? "Enabled" : "Disabled")}</div></div>`)}${section("Policy gate", "Research-only operating rules", `<div class="section-body"><div class="timeline"><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Read run-scoped evidence</div><div class="timeline-caption">Candidate, position, summary and provenance artifacts are normalized without mutation.</div></div><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Keep incomplete data visible</div><div class="timeline-caption">Missing forward evidence remains null; no synthetic PnL is shown.</div></div><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Block execution</div><div class="timeline-caption">Risk Governor and live execution are outside this console.</div></div></div></div>`)}</div>
    ${section("Provenance", "Hashes exposed for audit", `<div class="section-body">${provenanceList(appState.provenance)}</div>`)}`;
}

function runLogView() {
  const c = appState.cohort;
  const errors = c.errors || [];
  return `${pageHeader("RUN LOG", "Evidence timeline", "A compact record of what the current snapshot contains and what remains gated.", c.run_id)}
    <div class="page-grid">${section("Current run", "Discovery to validation", `<div class="section-body"><div class="timeline"><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Discovery snapshot</div><div class="timeline-caption">${c.markets_scanned} markets scanned, ${c.candidates} threshold candidates normalized.</div><div class="timeline-meta">${escapeHtml(c.entry_time)} · ${escapeHtml(c.discovery_schema)}</div></div><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Historical barrier verification</div><div class="timeline-caption">${c.historical_verified}/${c.historical_total} manifests verified; missing rule starts fail closed.</div><div class="timeline-meta">shared preload / tail / candle evidence</div></div><div class="timeline-item"><span class="timeline-marker"></span><div class="timeline-label">Offline validator</div><div class="timeline-caption">${c.positions} positions, ${c.closed_positions} closed, ${c.forward_observations} qualifying observations.</div><div class="timeline-meta">${escapeHtml(c.validator_schema)} · ${escapeHtml(c.status)}</div></div></div></div>`)}${section("Recorded warnings", "Non-fatal diagnostics", `<div class="section-body">${errors.length ? errors.map((error) => `<div class="notice warning"><span class="notice-mark">!</span><div><strong>Recoverable scan error</strong><span>${escapeHtml(error)}</span></div></div>`).join("") : `<div class="safety-note">No recorded discovery errors in this snapshot.</div>`}</div>`)}</div>`;
}

function renderView(view = currentView) {
  currentView = view;
  const labels = { overview: "Overview", cohort: "Cohort", markets: "Markets", safety: "Risk & safety", "run-log": "Run log" };
  $("#view-label").textContent = labels[view] || "Overview";
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  const app = $("#app-content");
  app.innerHTML = view === "cohort" ? cohortView() : view === "markets" ? marketsView() : view === "safety" ? safetyView() : view === "run-log" ? runLogView() : overview();
  if (view === "markets") {
    ["market-search", "market-filter", "asset-filter"].forEach((id) => $("#" + id)?.addEventListener(id === "market-search" ? "input" : "change", renderMarketTable));
    renderMarketTable();
  }
  $("#app-content").querySelectorAll("[data-view-jump]").forEach((button) => button.addEventListener("click", () => renderView(button.dataset.viewJump)));
}

function openDetail(type, id) {
  const row = type === "position" ? appState.positions.find((item) => item.shadow_trade_id === id) : appState.candidates.find((item) => item.market_id === id);
  if (!row) return;
  const isPosition = type === "position";
  $("#detail-title").textContent = row.question || "Market detail";
  const fields = isPosition ? [
    ["Asset", row.asset], ["Side", row.side], ["Status", row.status], ["Contract", row.contract_kind],
    ["Barrier", row.barrier_direction], ["Entry", row.entry_price === null ? "-" : number(row.entry_price, 4)],
    ["Expected edge", row.expected_edge === null ? "-" : percent(row.expected_edge, 2)], ["Confidence", row.confidence === null ? "-" : percent(row.confidence, 1)],
    ["Entry time", row.entry_time], ["Risk decision", row.risk_decision || "-"],
  ] : [
    ["Asset", row.asset], ["Side", row.side], ["Decision", row.recommended_action], ["Threshold", row.threshold_price === null ? "-" : `$${number(row.threshold_price, 2)}`],
    ["Barrier", row.barrier_direction], ["Contract", row.contract_kind], ["Expected edge", row.expected_edge === null ? "-" : percent(row.expected_edge, 2)], ["Confidence", row.confidence === null ? "-" : percent(row.confidence, 1)],
    ["Expiry", row.expiry_time], ["Historical", row.historical_status], ["Resolution", row.resolution_status], ["Spread", row.spread === null ? "-" : number(row.spread, 4)],
  ];
  const note = isPosition ? row.insufficient_reason || "No qualifying forward observation has been recorded." : row.risk_flags || row.historical_status;
  $("#detail-content").innerHTML = `<div class="detail-grid">${fields.map(([label, value]) => detailItem(label, value)).join("")}</div><div class="drawer-note">${escapeHtml(note || "No additional flags recorded.")}</div>`;
  $("#detail-drawer").classList.remove("hidden");
  $("#detail-drawer").setAttribute("aria-hidden", "false");
}

function closeDetail() {
  $("#detail-drawer").classList.add("hidden");
  $("#detail-drawer").setAttribute("aria-hidden", "true");
}

function updateShell() {
  const c = appState.cohort;
  $("#sidebar-status").textContent = c.status.replaceAll("_", " ");
  $("#sidebar-run").textContent = c.run_id;
  $("#snapshot-time").textContent = `Updated ${new Date(appState.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

async function loadState() {
  $("#loading-state").classList.remove("hidden");
  $("#error-state").classList.add("hidden");
  try {
    const response = await fetch(`/api/state?ts=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    appState = await response.json();
    updateShell();
    renderView(currentView);
    $("#app-content").classList.remove("hidden");
  } catch (error) {
    $("#error-message").textContent = `Unable to read the local snapshot: ${error.message}`;
    $("#error-state").classList.remove("hidden");
  } finally {
    $("#loading-state").classList.add("hidden");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.addEventListener("click", () => renderView(item.dataset.view)));
  $("#refresh-button").addEventListener("click", loadState);
  $("#retry-button").addEventListener("click", loadState);
  document.querySelectorAll("[data-close-drawer]").forEach((item) => item.addEventListener("click", closeDetail));
  $("#app-content").addEventListener("click", (event) => {
    const detail = event.target.closest("[data-detail-type]");
    if (detail) openDetail(detail.dataset.detailType, detail.dataset.detailId);
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeDetail(); });
  loadState();
});
