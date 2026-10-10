let readerName = null;
/* Tipping Point UI: one screen that tells the story without narration. */
const $ = (s) => document.querySelector(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

let cid = null, sample = null, loadedText = "", view = null, shownMsgs = 0, grid = null, lastFeed = -1, revealing = false;
let pollFails = 0, seenBuyerErrors = 0, settledShown = false;

const money = (v, cur) => v === "" || v == null ? "" : `${cur || view?.campaign.currency || "SGD"} ${Number(v).toFixed(2)}`;

// ---------------------------------------------------------------- feedback
function toast(msg, kind = "error", ms = 6000) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`; el.innerHTML = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 400); }, ms);
}

function explain(err) {
  const j = err.body || {};
  if (j.error === "paypal") return `PayPal sandbox rejected the request <b>${esc(j.issue || j.status)}</b>. Nothing else was changed; you can try again.`;
  if (j.error === "rule") return `Campaign settings: ${esc(j.detail)}`;
  if (j.error === "approval") return `The plan changed since you reviewed it. Please review it again.`;
  if (err.network) return `Can't reach the Tipping Point server. Is it still running?`;
  return esc(j.detail || err.message || "Something went wrong");
}

async function api(method, path, body) {
  let r;
  try {
    r = await fetch(path, {method, headers: {"Content-Type": "application/json"}, body: body ? JSON.stringify(body) : undefined});
  } catch (e) { const er = new Error("network"); er.network = true; throw er; }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { const er = new Error(j.detail || r.statusText); er.body = j; throw er; }
  return j;
}

// Run an action with a busy button; errors become toasts, never silent.
async function act(btn, busyLabel, fn) {
  const label = btn.innerHTML;
  btn.disabled = true; btn.classList.add("busy"); btn.innerHTML = `<span class="spin"></span>${busyLabel}`;
  try { return await fn(); }
  catch (e) { toast(explain(e)); }
  finally { btn.classList.remove("busy"); btn.innerHTML = label; if (view) render(view); else btn.disabled = false; }
}

// ---------------------------------------------------------------- setup
async function init() {
  try {
    const info = await api("GET", "/api/info");
    $("#mode").textContent = info.mode === "sandbox" ? "PayPal SANDBOX · real API" : "PayPal offline simulator";
    $("#mode").classList.toggle("sandbox", info.mode === "sandbox");
    readerName = info.reader;
    $("#reader").textContent = info.reader === "gemini" ? "Chat reader: Gemini" : "Chat reader: rules (offline)";
    $("#feedtitle").textContent = info.mode === "sandbox" ? "PayPal sandbox activity" : "PayPal activity (simulated)";
  } catch (e) { toast(explain(e)); }
  setupGrid();
  document.querySelectorAll("[data-sample]").forEach((b) => (b.onclick = () => loadSample(b.dataset.sample, b)));
  ["#paste", "#cfgItem", "#cfgMoq", "#cfgTiers"].forEach((s) => $(s).addEventListener("input", updateReadButton));
  $("#btnRead").onclick = () => act($("#btnRead"), readerName === "gemini" ? "Gemini is reading the chat…" : "Reading the chat…", readChat);
  $("#btnHolds").onclick = () => act($("#btnHolds"), "Creating PayPal holds…", async () => render(await api("POST", `/api/campaigns/${cid}/holds`)));
  $("#btnBuyers").onclick = () => act($("#btnBuyers"), "Starting buyers…", async () => render(await api("POST", `/api/campaigns/${cid}/demo-buyers`, {skip: new URLSearchParams(location.search).getAll("skip")})));
  $("#btnClose").onclick = () => act($("#btnClose"), "Working out the plan…", async () => {
    if (view.stage !== "closed") render(await api("POST", `/api/campaigns/${cid}/close`));
    showSettle();
  });
  $("#btnCancelSettle").onclick = () => $("#settle").classList.add("hidden");
  $("#btnApprove").onclick = () => act($("#btnApprove"), "Calling PayPal…", async () => {
    render(await api("POST", `/api/campaigns/${cid}/settle`, {plan_hash: view.plan.hash}));
    if (view.stage === "settled") { $("#settle").classList.add("hidden"); showResult(); }
    else { showSettle(); toast(`${view.settle_errors.length} PayPal call(s) failed. The others went through. Retrying is safe: calls that already succeeded will not run twice.`); }
  });
  $("#addmsg").onsubmit = (e) => {
    e.preventDefault(); const t = $("#addtext").value.trim(); if (!t) return;
    if (!t.includes(":")) { toast("Write it as  Name: message", "info"); return; }
    act($("#addmsg button"), "…", async () => { render(await api("POST", `/api/campaigns/${cid}/chat`, {text: t})); $("#addtext").value = ""; });
  };
  setInterval(poll, 1000);
  steps(0);
}

function parseTiers(s) {
  const out = [];
  for (const part of s.split(",").map((x) => x.trim()).filter(Boolean)) {
    const m = part.match(/^(\d+)\s*\+?\s*(?:@|:|=|for|at)?\s*\$?\s*(\d+(?:\.\d{1,2})?)$/i);
    if (!m) return null;
    out.push([Number(m[1]), m[2]]);
  }
  return out.length ? out : null;
}

function readConfig() {
  return {item: $("#cfgItem").value.trim() || "Group buy", moq: Number($("#cfgMoq").value), tiers: parseTiers($("#cfgTiers").value),
          variants: $("#cfgVariants").value.split(",").map((x) => x.trim()).filter(Boolean), organiser: $("#cfgOrganiser").value.trim()};
}

function updateReadButton() {
  const c = readConfig();
  const ok = $("#paste").value.trim() && c.moq > 0 && c.tiers;
  $("#btnRead").disabled = !ok;
  $("#settingsSummary").textContent = c.moq > 0 && c.tiers ? `· min ${c.moq} · ${c.tiers.map((t) => `${t[0]}+ @ ${t[1]}`).join(", ")}` : "· needed before reading";
  if ($("#paste").value.trim() && !(c.moq > 0 && c.tiers)) $("#settings").open = true;
}

function fillConfig(c) {
  $("#cfgItem").value = c.item; $("#cfgMoq").value = c.moq;
  $("#cfgTiers").value = c.tiers.map((t) => `${t.min_qty} @ ${t.unit_price}`).join(", ");
  $("#cfgVariants").value = c.variants.join(", "); $("#cfgOrganiser").value = c.organiser;
}

function resetScreen() {
  shownMsgs = 0; lastFeed = -1; seenBuyerErrors = 0; settledShown = false; view = null;
  $("#bubbles").classList.add("hidden"); $("#bubbles").innerHTML = ""; $("#paste").classList.remove("hidden"); $("#settings").classList.remove("hidden"); $("#readrow").classList.remove("hidden");
  $("#addmsg").classList.add("hidden"); $("#result").classList.add("hidden"); $("#settle").classList.add("hidden");
  $("#intro").classList.remove("hidden"); $("#campaignBody").classList.add("hidden");
  grid.setGridOption("rowData", []); grid.setGridOption("pinnedBottomRowData", []);
  $("#issues").innerHTML = `<div class="empty">Unclear messages (maybes, questions, orders placed for someone else) show up here with a reply drafted for you.</div>`;
  $("#issuecount").classList.add("hidden");
  $("#feed").innerHTML = `<div class="empty">Every PayPal API call appears here as it happens.</div>`;
  ["#btnHolds", "#btnBuyers", "#btnClose"].forEach((b) => ($(b).disabled = true));
}

async function loadSample(name, btn) {
  if (view?.demo_running) { toast("Buyers are still approving on PayPal. Wait for them to finish first.", "info"); return; }
  await act(btn, name === "socks" ? "House socks" : name === "durian" ? "Durian puffs" : "Keycaps", async () => {
    const r = await api("POST", "/api/campaigns", {sample: name});
    resetScreen(); sample = name; cid = r.id; loadedText = r.chat_text;
    fillConfig(r.view.campaign); updateReadButton();
    const t = loadedText; $("#paste").value = "";
    for (let i = 1; i <= 12; i++) { $("#paste").value = t.slice(0, Math.ceil(t.length * i / 12)); await sleep(40); }
    updateReadButton(); steps(1);
  });
}

async function readChat() {
  const cfg = readConfig();
  const r = await api("POST", "/api/campaigns", {sample: $("#paste").value === loadedText ? sample : sample, chat_text: $("#paste").value, config: cfg});
  cid = r.id; loadedText = r.chat_text;
  const v = await api("POST", `/api/campaigns/${cid}/read`);
  if (!v.messages.length) { toast("I couldn't find any messages in that text. Paste a WhatsApp “Export chat” file or a Telegram JSON export.", "error", 8000); return; }
  $("#paste").classList.add("hidden"); $("#settings").classList.add("hidden"); $("#readrow").classList.add("hidden");
  $("#bubbles").classList.remove("hidden"); $("#addmsg").classList.remove("hidden");
  $("#intro").classList.add("hidden"); $("#campaignBody").classList.remove("hidden");
  if (v.reader_note) toast(esc(v.reader_note), "info", 8000);
  if (v.reader_used) $("#reader").textContent = v.reader_used === "gemini" ? "Read by Gemini" : (readerName === "gemini" ? "Chat reader: rules (Gemini unavailable)" : "Chat reader: rules (offline)");
  revealing = true; view = v; renderCampaign(v, true);
  await revealBubbles(v.messages);
  revealing = false; render(v);
  if (!v.rows.length) toast("The chat has messages but no orders I could read. Check the options and organiser in Campaign settings.", "info", 8000);
}

function bubble(m) {
  const chips = m.chips.map((c) => `<span class="chip ${c.kind}">${esc(c.text)}${c.who ? ` <span class="for">for ${esc(c.who)}</span>` : ""}</span>`).join("");
  const el = document.createElement("div");
  el.className = `b ${m.cls}`;
  el.innerHTML = `<div class="who">${esc(m.sender)}<span class="time">${esc(m.time)}</span></div><div class="txt">${esc(m.text)}</div>${chips ? `<div class="chips">${chips}</div>` : ""}`;
  return el;
}

async function revealBubbles(msgs) {
  const box = $("#bubbles");
  for (let i = shownMsgs; i < msgs.length; i++) {
    box.appendChild(bubble(msgs[i])); box.scrollTop = box.scrollHeight;
    await sleep(msgs[i].cls === "chatter" ? 90 : 260);
  }
  shownMsgs = msgs.length;
}

function setupGrid() {
  const statusCell = (p) => {
    const s = p.value || "";
    if (p.node.rowPinned) return "";
    const cls = s.startsWith("TOP") ? "TOPUP" : s.startsWith("AWAIT") ? "AWAITING" : s.startsWith("NOT") ? "NOT" : s.startsWith("NO LINK") ? "NOLINK" : s.startsWith("PAYPAL") ? "ERR" : s;
    const ids = (p.data.auth_ids || []).join(" + ");
    return `<span class="st st-${cls}">${esc(s)}</span>${ids ? ` <span class="aid">${esc(ids)}</span>` : ""}`;
  };
  grid = agGrid.createGrid($("#grid"), {
    columnDefs: [
      {field: "participant", headerName: "Buyer", flex: 1.3, minWidth: 110, tooltipField: "participant", cellRenderer: (p) => `${esc(p.value)}${p.data.added_by ? ` <span class="via">via organiser</span>` : ""}`},
      {field: "items", headerName: "Order", flex: 1, minWidth: 70},
      {field: "qty", headerName: "Qty", width: 62, suppressSizeToFit: true, type: "numericColumn"},
      {field: "hold_amount", headerName: "Held", width: 78, suppressSizeToFit: true, type: "numericColumn", valueFormatter: (p) => Number(p.value) ? Number(p.value).toFixed(2) : "", enableCellChangeFlash: true},
      {field: "status", headerName: "Status · PayPal authorization", flex: 1.7, minWidth: 150, tooltipValueGetter: (p) => (p.data.auth_ids || []).join(" + "), cellRenderer: statusCell, enableCellChangeFlash: true},
      {field: "captured", colId: "captured", headerName: "Charged", width: 88, suppressSizeToFit: true, type: "numericColumn", valueFormatter: (p) => p.value === "" ? "" : Number(p.value).toFixed(2), cellStyle: {fontWeight: 700}, hide: true},
      {field: "released", colId: "released", headerName: "Released", width: 88, suppressSizeToFit: true, type: "numericColumn", valueFormatter: (p) => p.value === "" ? "" : Number(p.value).toFixed(2), hide: true},
    ],
    rowData: [], getRowId: (p) => p.data.participant, animateRows: true,
    defaultColDef: {sortable: true, resizable: true},
    overlayNoRowsTemplate: `<span class="empty">The order list appears here once the chat is read.</span>`,
    autoSizeStrategy: {type: "fitGridWidth"},
  });
}

// ---------------------------------------------------------------- render
function renderCampaign(v, beforeReveal) {
  const c = v.campaign, p = v.progress;
  const linksOut = v.rows.some((r) => r.links.length);
  $("#item").textContent = `${c.item} · minimum ${c.moq}`;
  const left = new Date(c.deadline) - Date.now();
  $("#deadline").textContent = v.stage === "settled" ? "settled" : v.stage === "closed" ? "closed" : left > 0 ? `closes in ${Math.floor(left / 3600e3)}h ${Math.floor(left / 60e3) % 60}m` : "deadline passed";
  const counted = beforeReveal ? 0 : (linksOut ? p.held : p.committed);
  const max = Math.max(c.tiers[c.tiers.length - 1].min_qty * 1.2, c.moq * 1.5, p.committed * 1.1);
  const pct = (n) => `${Math.min(100, (n / max) * 100)}%`;
  $("#fillCommitted").style.width = beforeReveal ? "0%" : pct(p.committed);
  $("#fillHeld").style.width = beforeReveal ? "0%" : pct(p.held);
  $("#markers").innerHTML = c.tiers.map((t, i) => {
    const isMoq = i === 0;
    const at = isMoq ? c.moq : t.min_qty;
    return `<div class="mk ${isMoq ? "moq" : "tier"} ${linksOut && counted >= at ? "reached" : ""}" style="left:${pct(at)}"><span>${isMoq ? `MINIMUM ${at} · ${money(t.unit_price, c.currency)} each` : `${at}+ → ${money(t.unit_price, c.currency)}`}</span></div>`;
  }).join("");
  $("#bignum").textContent = counted;
  $("#bigof").textContent = ` / ${c.moq} ${linksOut ? "held" : "said yes"}`;
  const pill = $("#bigpill"); pill.className = "pill";
  if (v.stage === "settled" && v.plan) {
    if (v.plan.outcome === "TIPPED") { pill.classList.add("tipped"); pill.textContent = `TIPPED · charged ${money(v.plan.unit_price)} each`; }
    else { pill.classList.add("failed"); pill.textContent = `MISSED BY ${v.plan.shortfall} · nobody charged`; }
  } else if (beforeReveal) { pill.classList.add("short"); pill.textContent = "reading…"; }
  else if (!linksOut) { pill.classList.add("short"); pill.textContent = p.committed >= c.moq ? `enough interest · now make it real with holds` : `${c.moq - p.committed} more needed`; }
  else if (counted >= c.moq) { pill.classList.add("tipped"); pill.textContent = `TIPPED ✓ group price ${money(p.unit_now)}`; }
  else { pill.classList.add("short"); pill.textContent = `${c.moq - counted} to go`; }
  $("#bignum").style.color = counted >= c.moq && linksOut ? "var(--green)" : "";
}

function render(v) {
  view = v;
  if (revealing || $("#campaignBody").classList.contains("hidden") && v.stage === "draft") return;
  renderCampaign(v, false);
  if (v.messages.length > shownMsgs && !$("#bubbles").classList.contains("hidden")) revealBubbles(v.messages);
  const settled = v.stage === "settled";
  grid.setColumnsVisible(["captured", "released"], settled);
  grid.setGridOption("rowData", v.rows);
  const t = v.totals;
  grid.setGridOption("pinnedBottomRowData", v.rows.length ? [{participant: "Total", items: "", qty: v.progress.committed, hold_amount: t.held, status: "", captured: settled ? t.captured : "", released: t.released ?? "", auth_ids: []}] : []);
  grid.sizeColumnsToFit();
  // issues
  if (v.issues.length) {
    $("#issues").innerHTML = v.issues.map((i) => `<div class="issue"><div class="k">${esc(i.kind.replace(/_/g, " "))} · ${esc(i.participant)}</div>${esc(i.detail)}<div class="draft">Suggested reply: “${esc(i.draft_reply)}”</div></div>`).join("");
    $("#issuecount").textContent = v.issues.length; $("#issuecount").classList.remove("hidden");
  } else if (v.stage !== "draft") {
    $("#issues").innerHTML = `<div class="empty ok">✓ Every message was understood.</div>`; $("#issuecount").classList.add("hidden");
  }
  // feed
  if (v.activity.length !== lastFeed) {
    $("#feed").innerHTML = v.activity.length ? v.activity.slice().reverse().map((a) =>
      `<div class="f"><span class="m">${a.method}</span> ${esc(a.path.replace("/v2/", "").replace("checkout/", "").replace("payments/", ""))} <span class="${a.status < 400 ? "ok" : "bad"}">${a.status} ${esc(a.summary || "")}</span>${a.amount ? ` · ${money(a.amount)}` : ""}</div>`).join("")
      : `<div class="empty">Every PayPal API call appears here as it happens.</div>`;
    lastFeed = v.activity.length;
  }
  // buyer progress + failures
  const dp = v.demo_progress;
  if (v.demo_running && dp) {
    $("#progress").classList.remove("hidden");
    $("#progress").innerHTML = `<span class="spin"></span>Buyer ${Math.min(dp.done + 1, dp.total)} of ${dp.total}${dp.current ? ` · <b>${esc(dp.current)}</b>` : ""} is approving on PayPal…<div class="pbar"><div style="width:${(dp.done / dp.total) * 100}%"></div></div>`;
  } else $("#progress").classList.add("hidden");
  const fails = (v.demo_log || []).filter((d) => !d.ok);
  for (const f of fails.slice(seenBuyerErrors)) toast(`${esc(f.participant || "A buyer")} didn't finish approving on PayPal. Their link is still open; press “Play buyers” to try again.`, "info", 8000);
  seenBuyerErrors = fails.length;
  // buttons + steps
  const anyNeeds = v.rows.some((r) => r.status === "NO LINK YET" || r.status === "TOP-UP NEEDED");
  const awaiting = v.rows.some((r) => r.status === "AWAITING BUYER");
  const idle = (b) => !$(b).classList.contains("busy");
  if (idle("#btnHolds")) {
    $("#btnHolds").disabled = !(v.stage === "read" || (v.stage === "collecting" && anyNeeds)) || v.demo_running || !v.rows.length;
    $("#btnHolds").textContent = v.stage === "collecting" && anyNeeds ? "Send top-up links" : "Send hold links";
    $("#btnHolds").classList.toggle("go", !$("#btnHolds").disabled);
  }
  if (idle("#btnBuyers")) {
    $("#btnBuyers").disabled = !(v.stage === "collecting" && awaiting) || v.demo_running;
    $("#btnBuyers").textContent = v.demo_running ? "Buyers approving on PayPal…" : "▶ Play buyers (sandbox)";
  }
  if (idle("#btnClose")) {
    $("#btnClose").disabled = !(v.stage === "collecting" || v.stage === "closed") || v.demo_running;
    $("#btnClose").textContent = v.stage === "closed" ? "Review settlement" : "Close campaign";
    $("#btnClose").classList.toggle("go", (v.stage === "collecting" && !awaiting) || v.stage === "closed");
  }
  steps({draft: 1, read: 2, collecting: awaiting || v.demo_running ? 3 : 4, closed: 5, settled: 99}[v.stage]);
  if (settled && !settledShown && $("#settle").classList.contains("hidden")) showResult();
}

function steps(idx) {
  document.querySelectorAll("#steps li").forEach((li, i) => { li.classList.toggle("done", i < idx); li.classList.toggle("now", i === idx); });
}

function showSettle() {
  const pl = view.plan, c = view.campaign;
  $("#settleHead").innerHTML = pl.outcome === "TIPPED"
    ? `<h2>The group tipped at ${pl.total_qty}. Everyone pays ${money(pl.unit_price)} each</h2><p>Holds were placed at ${money(c.hold_unit_price)}. Each hold is captured at the group price; PayPal releases the rest automatically.</p>`
    : `<h2>Missed the minimum by ${pl.shortfall}. Release every hold</h2><p>${pl.total_qty} of ${c.moq} held. Every authorization is voided: nobody is charged and there is nothing to refund.</p>`;
  const errs = view.settle_errors || [];
  $("#settleErrors").classList.toggle("hidden", !errs.length);
  $("#settleErrors").innerHTML = errs.length ? `<b>${errs.length} PayPal call(s) failed:</b> ${errs.map((e) => `${esc(e.participant)} (${esc(e.action)}: ${esc(e.issue)})`).join(", ")}. Retrying is safe: the same request IDs are reused, so calls that already succeeded will not run twice.` : "";
  const failed = new Set(errs.map((e) => e.participant));
  $("#settleActions").innerHTML = pl.actions.map((a) => `<div class="act ${failed.has(a.participant) ? "failed" : ""}"><span class="kind ${a.kind}">${a.kind === "void" ? "release" : a.kind}</span><span>${esc(a.participant)}<code>${a.request ? esc(a.request.method + " " + a.request.path + (a.request.body ? " " + JSON.stringify(a.request.body) : "")) : esc(a.reason)}</code></span><span class="amt">${a.amount ? money(a.amount) : ""}</span></div>`).join("") || `<div class="empty">No holds were placed, so there is nothing for PayPal to do.</div>`;
  $("#btnApprove").textContent = errs.length ? "Retry failed calls" : "Approve & execute";
  $("#hashline").textContent = `You are approving exactly this plan · sha256 ${pl.hash.slice(0, 16)}… · if anything changes, the approval no longer applies`;
  $("#settle").classList.remove("hidden");
}

function showResult() {
  settledShown = true;
  const t = view.totals, pl = view.plan;
  $("#result").className = `result ${pl.outcome === "TIPPED" ? "tipped" : "failed"}`;
  $("#result").innerHTML = pl.outcome === "TIPPED"
    ? `${money(t.captured)} charged · ${money(t.released)} released back to buyers<small>Held at ${money(view.campaign.hold_unit_price)}, charged at the group price of ${money(pl.unit_price)}. No refunds needed.</small>`
    : `Nobody was charged · ${money(t.released)} in holds released<small>The group was ${pl.shortfall} short of the minimum of ${view.campaign.moq}. No refunds needed.</small>`;
  $("#result").classList.remove("hidden");
}

async function poll() {
  if (!cid || revealing || !view || view.stage === "draft") return;
  try {
    render(await api("GET", `/api/campaigns/${cid}`));
    if (pollFails) $("#conn").classList.add("hidden");
    pollFails = 0;
  } catch (e) {
    if (++pollFails >= 3) $("#conn").classList.remove("hidden");
  }
}

init();
