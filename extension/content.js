(() => {
  if (document.getElementById("forge-companion")) return;
  const host = document.createElement("div");
  host.id = "forge-companion";
  host.style.cssText = "all:initial;position:fixed;inset:0;z-index:2147483000;pointer-events:none;";
  const root = host.attachShadow({mode: "open"});
  const sheet = document.createElement("link");
  sheet.rel = "stylesheet"; sheet.href = chrome.runtime.getURL("panel.css"); root.append(sheet);
  const surface = document.createElement("div"); surface.className = "forge"; root.append(surface);
  document.documentElement.append(host);

  const icon = (name, size = 18) => {
    const paths = {
      forge: '<path d="M6 5h12M6 11h9M6 5v14"/><path d="m14 15 3 3 4-6"/>',
      close: '<path d="m6 6 12 12M6 18 18 6"/>',
      arrow: '<path d="M7 17 17 7M7 7h10v10"/>',
      chevron: '<path d="m9 5 7 7-7 7"/>',
      check: '<path d="m5 12 4 4L19 6"/>',
      settings: '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>',
      clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/>',
      code: '<path d="m8 7-5 5 5 5m8-10 5 5-5 5m-3-13-2 16"/>',
      shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
      file: '<path d="M14 3H6v18h12V7l-4-4Z"/><path d="M14 3v5h4M9 12h6m-6 4h6"/>',
      play: '<path d="m9 5 11 7-11 7V5Z"/>',
      history: '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7m2-4v5l3 2"/>',
      download: '<path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4"/>',
      back: '<path d="m14 6-6 6 6 6"/>',
      sparkle: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5L12 3Z"/>',
      warn: '<path d="m12 3 10 18H2L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
    };
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;
  };
  const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[char]));
  const call = async (action, values = {}) => {
    const response = await chrome.runtime.sendMessage({type: "forge", action, ...values});
    if (!response?.ok) throw new Error(response?.error || "Forge could not complete this request.");
    return response.data;
  };
  const state = {open: false, tab: "progress", run: null, service: null, error: "", busy: false,
    history: null, confirm: false, revision: false, route: location.pathname, selectedFile: 0, selectedCheck: 0};
  let timer;
  const activeStatuses = ["queued", "snapshotting", "indexing", "baseline", "planning", "coding", "testing", "validating", "reviewing", "repairing", "publishing"];
  const phases = [
    ["Explore", ["queued", "snapshotting", "indexing", "baseline"]],
    ["Plan", ["planning"]], ["Code", ["coding", "testing", "repairing"]],
    ["Test", ["validating"]], ["Review", ["reviewing"]],
  ];
  const label = status => ({awaiting_approval: "Ready for review", demo_complete: "Demo complete", pr_opened: "Draft PR created",
    snapshotting: "Reading repository", indexing: "Exploring code", baseline: "Checking the baseline", planning: "Planning the change",
    coding: "Writing the change", testing: "Preparing regression tests", validating: "Running checks", reviewing: "Reviewing the proposal",
    repairing: "Repairing the candidate", queued: "Queued", publishing: "Publishing approved changes", failed: "Needs attention",
    cancelled: "Cancelled", rejected: "Proposal rejected", stale: "Base branch changed", needs_input: "Needs your input"}[status] || status);
  const context = () => {
    const match = location.pathname.match(/^\/([\w.-]+)\/([\w.-]+)(?:\/(issues|pull)\/(\d+))?/);
    return match ? {repo: `${match[1]}/${match[2]}`, issue: match[3] === "issues" ? Number(match[4]) : null} : {repo: null, issue: null};
  };
  const button = (action, text, cls = "", symbol = "") => `<button type="button" data-action="${action}" class="${cls}" ${state.busy ? "disabled" : ""}>${symbol ? icon(symbol, 16) : ""}${text}</button>`;
  function theme() {
    const mode = document.documentElement.dataset.colorMode;
    surface.dataset.theme = mode === "dark" || mode === "auto" && matchMedia("(prefers-color-scheme:dark)").matches ? "dark" : "light";
  }

  function landing() {
    const ctx = context();
    const title = document.querySelector('[data-testid="issue-title"], .js-issue-title, bdi.markdown-title')?.textContent?.trim();
    const ready = state.service?.github && state.service?.model && state.service?.runner;
    return `<div class="landing">
      <div class="intro-visual" aria-hidden="true"><span class="orbit one"></span><span class="orbit two"></span><span class="orbit three"></span><span class="hero-mark">${icon("forge", 38)}</span><i class="orbit-dot a"></i><i class="orbit-dot b"></i></div>
      <div class="eyebrow">A THOUGHTFUL PAIR OF HANDS</div>
      <h1>From issue<br>to possibility.</h1>
      <p class="lede">The context, the code, the checks.<br>Forge does the groundwork. You make the call.</p>
      <div class="issue-card"><div class="issue-label"><span class="issue-icon">◉</span> ${ctx.issue ? "THIS ISSUE" : "YOUR NEXT CHANGE"}<span class="mono">${ctx.issue ? "#" + ctx.issue : ""}</span></div>
        <h2>${esc(ctx.issue ? title || "GitHub issue #" + ctx.issue : "Open an issue to begin")}</h2>
        <p>${esc(ctx.repo || "github.com")} <span>·</span> ${ctx.issue ? "Default branch" : "GitHub companion"}</p>
      </div>
      ${ctx.issue ? button("start", "Start Forge", "primary wide", "arrow") : ""}
      <div class="mini-flow"><span>Explore</span><i>→</i><span>Build</span><i>→</i><span>Verify</span><i>→</i><strong>You approve</strong></div>
      <div class="safety-note">${icon("shield", 17)}<span>No commits or pull requests until you approve the exact changes.</span></div>
      ${!ready ? `<div class="setup-note"><span class="small-dot"></span><p>${state.service ? "Repository runs need a GitHub App, a free model and GitHub Actions access." : "Connect to your local Forge service to get started."}</p>${button("options", "Connection", "text-button")}</div>` : ""}
      <div class="demo-card"><span class="demo-symbol">${icon("play", 18)}</span><div><strong>Take a small test drive</strong><p>A bundled issue. Real checks. No GitHub writes.</p></div>${button("demo", '<span class="sr-only">Run bundled demo</span>', "icon-button", "arrow")}</div>
    </div>`;
  }

  function runHeader() {
    const r = state.run;
    const isActive = activeStatuses.includes(r.status);
    return `<div class="run-heading"><div class="run-meta"><span class="mono">${esc(r.repo)}</span><span>#${r.issue}</span></div>
      <h1>${esc(r.title)}</h1>
      <div class="status-line"><span class="status-pill ${isActive ? "live" : ["failed", "stale"].includes(r.status) ? "attention" : ""}"><span class="small-dot"></span>${label(r.status)}</span>
      ${r.mode === "demo" ? '<span class="demo-pill">BUNDLED DEMO</span>' : ""}</div>
      ${r.mode === "demo" ? '<p class="demo-disclosure">Scripted agent steps · actual Python checks · no model calls</p>' : ""}
    </div>`;
  }

  function progress() {
    const r = state.run;
    const events = r.events || [];
    const completed = ["awaiting_approval", "publishing", "pr_opened", "demo_complete"].includes(r.status);
    let current = phases.findIndex(([, statuses]) => statuses.includes(r.status));
    if (current < 0) current = completed ? 5 : Math.max(0, phases.findIndex(([, statuses]) => statuses.includes(events.at(-2)?.kind)));
    return `<div class="phase-track">${phases.map(([name], i) => `<div class="phase ${i < current ? "done" : i === current ? "current" : ""}"><span>${i < current ? icon("check", 12) : i + 1}</span><label>${name}</label></div>`).join("")}</div>
      ${r.plan ? `<section class="section"><div class="section-label">THE APPROACH <span>${icon("sparkle", 14)}</span></div><p class="plan-summary">${esc(r.plan.summary)}</p><ol class="plan-steps">${r.plan.steps.map(s => `<li>${esc(s)}</li>`).join("")}</ol></section>` : `<div class="working-card">${icon("code", 23)}<div><strong>${label(r.status)}</strong><p>Gathering the evidence for a focused change.</p></div></div>`}
      ${r.plan ? `<section class="section"><div class="section-label">WHAT GOOD LOOKS LIKE</div><ul class="acceptance">${r.plan.acceptance.map(s => `<li><span>↳</span>${esc(s)}</li>`).join("")}</ul></section>` : ""}
      ${r.index?.files?.length ? `<section class="section"><div class="section-label">RELEVANT FILES <span>${r.index.file_count} indexed</span></div><div class="file-pills">${r.index.files.slice(0, 6).map(f => r.mode === "demo" ? `<span>${icon("file", 12)}${esc(f.path)}</span>` : `<a href="https://github.com/${esc(r.repo)}/blob/${esc(r.context.base_sha)}/${f.path.split("/").map(encodeURIComponent).join("/")}#L${f.start_line}-L${f.end_line}" target="_blank" rel="noopener noreferrer">${icon("file", 12)}${esc(f.path)}</a>`).join("")}</div></section>` : ""}
      <section class="section"><div class="section-label">ACTIVITY <span>${events.length} events</span></div><div class="timeline">${events.slice(-8).map((e, i, a) => `<div class="timeline-item ${i === a.length - 1 ? "latest" : ""}"><span class="timeline-dot"></span><div><p>${esc(e.message)}</p><time>${new Date(e.created * 1000).toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"})}</time></div></div>`).join("")}</div></section>
      ${r.review ? `<div class="review-note">${icon("shield", 19)}<div><strong>Reviewer’s note</strong><p>${esc(r.review.summary)}</p>${r.review.findings.map(f => `<p>${esc(f)}</p>`).join("")}</div></div>` : ""}
      <section class="section"><div class="section-label">EXECUTION RECORD <span>Free access only</span></div><div class="execution-record"><span>Model</span><code>${esc(r.model || "Not called yet")}</code><span>Calls / tokens</span><code>${r.usage?.calls || 0} / ${(r.usage?.tokens || 0).toLocaleString()}</code><span>Base revision</span><code>${esc(r.context?.base_sha?.slice(0, 12) || "Pending")}</code></div></section>`;
  }

  function changes() {
    const candidate = state.run.candidate;
    if (!candidate) return `<div class="empty-state">${icon("code", 28)}<h2>The change is taking shape.</h2><p>The proposed diff will appear here after validation.</p></div>`;
    const files = candidate.changes;
    state.selectedFile = Math.min(state.selectedFile, files.length - 1);
    const file = files[state.selectedFile];
    const patch = candidate.patch;
    // Display exact unified diff hunks for the selected file, with escaped source text.
    const selected = patch.split(/(?=^--- (?:a\/|\/dev\/null))/m).find(chunk =>
      chunk.startsWith(`--- a/${file.path}\n`) || chunk.startsWith(`--- /dev/null\n+++ b/${file.path}\n`)) || "";
    const added = patch.split("\n").filter(l => l.startsWith("+") && !l.startsWith("+++")).length;
    const removed = patch.split("\n").filter(l => l.startsWith("-") && !l.startsWith("---")).length;
    return `<div class="change-summary"><span>${files.length} files changed</span><span><b class="added">+${added}</b> <b class="removed">−${removed}</b></span></div>
      <div class="file-list">${files.map((f, i) => `<button data-file="${i}" class="file-row ${i === state.selectedFile ? "selected" : ""}">${icon("file", 15)}<span>${esc(f.path)}</span><span class="file-kind">${f.before == null ? "A" : f.after == null ? "D" : "M"}</span></button>`).join("")}</div>
      <div class="diff-box"><div class="diff-title">${icon("code", 14)}${esc(file.path)}</div><pre aria-label="Proposed file diff">${selected.split("\n").map(line => `<span class="diff-line ${line.startsWith("@@") ? "hunk" : line.startsWith("+") && !line.startsWith("+++") ? "addition" : line.startsWith("-") && !line.startsWith("---") ? "deletion" : ""}">${esc(line) || " "}</span>`).join("")}</pre></div>
      <div class="fingerprint"><span>CANDIDATE FINGERPRINT</span><code title="${candidate.fingerprint}">${candidate.fingerprint.slice(0, 16)}…</code></div>
      <div class="fingerprint"><span>PINNED BASE REVISION</span><code>${esc(candidate.base_sha.slice(0, 12))}</code></div>
      ${button("download", "Download exact patch", "secondary wide", "download")}`;
  }

  function checks() {
    const list = state.run.checks || [];
    if (!list.length) return `<div class="empty-state">${icon("shield", 30)}<h2>Evidence comes first.</h2><p>Commands, exit codes, and test output will appear here as checks finish.</p></div>`;
    return `<p class="tab-intro">Executed results, kept with the exact revision. A failing regression on the original code is expected.</p>
      <div class="checks-list">${list.map((c, i) => `<details class="check-card" ${i === list.length - 1 ? "open" : ""}><summary><span class="check-symbol ${c.status === "passed" ? "pass" : "fail"}">${icon(c.status === "passed" ? "check" : "warn", 15)}</span><div><strong>${esc(c.phase === "regression_on_base" ? "Regression · original code" : c.phase === "baseline" ? "Baseline · original code" : "Candidate · proposed change")}</strong><span>${c.count} tests · ${c.seconds}s · exit ${c.exit_code}</span></div><span class="result-label ${c.status}">${c.status === "failed" && c.phase === "regression_on_base" ? "Reproduced" : esc(c.status)}</span></summary><div class="check-detail"><code>${esc(c.command)}</code><p>${esc(c.environment)}</p><pre>${esc(c.output)}</pre></div></details>`).join("")}</div>
      <div class="evidence-note">${icon("shield", 18)}<p>Passing tests support this proposal. They don’t replace your review.</p></div>`;
  }

  function approvalFooter() {
    const r = state.run;
    if (!r) return `<footer class="bottom-bar"><span class="small-dot"></span> YOUR REPOSITORY. YOUR CALL.<span>v0.2</span></footer>`;
    if (r.status === "awaiting_approval") {
      if (r.mode !== "demo" && r.approval_expires_at && Date.now() / 1000 > r.approval_expires_at) {
        return `<footer class="approval-footer"><div class="approval-label">${icon("clock", 16)}This review window expired. Fresh validation is needed.</div>${button("refresh", "Refresh proposal and checks", "primary wide", "arrow")}<div class="footer-actions">${button("reject", "Reject", "text-button")}${button("download", "Download old patch", "text-button")}</div></footer>`;
      }
      return `<footer class="approval-footer"><div class="approval-label">${icon("shield", 16)}${r.mode === "demo" ? "Demo ready. Nothing will be published." : "Your approval unlocks a commit and draft PR."}</div>
      ${state.revision ? `<label class="revision-label" for="forge-feedback">What should change?</label><textarea id="forge-feedback" rows="3" maxlength="4000" placeholder="Describe the correction or missing requirement…"></textarea>${button("submit-revision", "Request a fresh proposal", "secondary wide", "arrow")}` : ""}
      ${state.confirm && r.mode !== "demo" ? `<label class="consent"><input type="checkbox" id="forge-ci-consent">I reviewed the diff and checks. Publishing may trigger repository CI.</label>` : ""}
      ${button(state.confirm || r.mode === "demo" ? "approve" : "review-approve", r.mode === "demo" ? "Approve demo proposal" : state.confirm ? "Confirm and create draft PR" : "Approve and create draft PR", "primary wide", "check")}
      <div class="footer-actions">${button("reject", "Reject", "text-button")}${r.mode !== "demo" ? button("revision", state.revision ? "Cancel revision" : "Request revision", "text-button") : ""}${button("download", "Download patch", "text-button")}</div></footer>`;
    }
    if (r.status === "demo_complete" || r.status === "pr_opened") {
      const url = r.publication?.pr_url;
      return `<footer class="approval-footer"><div class="completion">${icon("check", 18)}${r.status === "demo_complete" ? "Demo complete. No GitHub changes made." : "Your draft pull request is ready."}</div>
        ${url && /^https:\/\/github.com\/[\w.-]+\/[\w.-]+\/pull\/\d+$/.test(url) ? `<a class="primary wide" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Open draft pull request ${icon("arrow", 16)}</a>` : button("new", "Back to this issue", "secondary wide", "back")}</footer>`;
    }
    if (activeStatuses.includes(r.status)) return `<footer class="run-footer"><span>${icon("clock", 13)} ${elapsed(r.created)}</span><span>${r.repairs || 0}/2 repairs</span>${button("cancel", "Cancel run", "text-button")}</footer>`;
    return `<footer class="approval-footer">${button("new", "Back to this issue", "secondary wide", "back")}</footer>`;
  }
  function elapsed(created) {
    const seconds = Math.max(0, Math.floor(Date.now() / 1000 - created));
    return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s`;
  }

  function historyView() {
    return `<div class="history-heading"><p class="eyebrow">YOUR RECENT WORK</p><h1>A trail of progress.</h1></div><div class="history-list">${state.history.length ? state.history.map(r => `<button class="history-row" data-run="${r.id}"><span class="history-run-icon">${icon(r.status === "pr_opened" || r.status === "demo_complete" ? "check" : "code", 17)}</span><div><strong>${esc(r.title)}</strong><p>${esc(r.repo)} · #${r.issue}</p><span>${label(r.status)}${r.mode === "demo" ? " · Demo" : ""}</span></div>${icon("chevron", 15)}</button>`).join("") : '<div class="empty-state"><h2>A fresh start.</h2><p>Your proposals will appear here.</p></div>'}</div>`;
  }

  function render() {
    const focusAction = root.activeElement?.dataset?.action;
    const scrollTop = root.querySelector(".panel-body")?.scrollTop || 0;
    const top = `<header class="topbar"><div class="wordmark"><span class="brand-mark">${icon("forge", 21)}</span><strong>forge</strong><span class="product-tag">GITHUB COMPANION</span></div><div class="top-actions">${button("history", '<span class="sr-only">Recent runs</span>', "icon-button", "history")}${button("options", '<span class="sr-only">Connection settings</span>', "icon-button", "settings")}${button("close", '<span class="sr-only">Close Forge</span>', "icon-button", "close")}</div></header>`;
    surface.innerHTML = `<button class="launcher ${state.open ? "hidden" : ""}" data-action="open" aria-label="Open Forge">${icon("forge", 20)}<strong>Forge</strong><span class="launcher-dot"></span></button>
      <aside class="panel ${state.open ? "is-open" : ""}" aria-label="Forge engineering companion" ${state.open ? "" : "inert"}>
      ${top}${state.error ? `<div class="error-banner" role="alert">${icon("warn", 16)}<span>${esc(state.error)}</span>${button("dismiss", '<span class="sr-only">Dismiss message</span>', "icon-button", "close")}</div>` : ""}
      ${state.run && !state.history ? runHeader() + `<div class="tabs" role="tablist" aria-label="Run views">${["progress", "changes", "checks"].map(t => `<button role="tab" aria-selected="${state.tab === t}" tabindex="${state.tab === t ? 0 : -1}" data-tab="${t}" id="forge-tab-${t}" aria-controls="forge-tabpanel">${t[0].toUpperCase() + t.slice(1)}${t === "changes" && state.run.candidate ? `<span>${state.run.candidate.changes.length}</span>` : ""}</button>`).join("")}</div>` : ""}
      <div class="panel-body" ${state.run && !state.history ? `role="tabpanel" id="forge-tabpanel" aria-labelledby="forge-tab-${state.tab}"` : ""}>
      ${state.history ? historyView() : state.run ? `${state.run.error ? `<div class="run-error"><strong>The run stopped here.</strong><p>${esc(state.run.error)}</p></div>` : ""}${state.run.limitations?.map(l => `<p class="limitation">${esc(l)}</p>`).join("") || ""}${state.tab === "progress" ? progress() : state.tab === "changes" ? changes() : checks()}` : landing()}</div>
      ${state.history ? `<footer class="approval-footer">${button("back", "Back", "secondary wide", "back")}</footer>` : approvalFooter()}</aside>`;
    theme();
    const body = root.querySelector(".panel-body"); if (body) body.scrollTop = scrollTop;
    if (focusAction) root.querySelector(`[data-action="${focusAction}"]`)?.focus({preventScroll: true});
  }

  async function loadRun(id) {
    state.run = await call("run", {id});
    render();
    clearTimeout(timer);
    if (state.open && activeStatuses.includes(state.run.status)) timer = setTimeout(() => loadRun(id).catch(error => {state.error = error.message; render();}), 1400);
  }
  async function open() {
    state.open = true; render(); root.querySelector('[data-action="close"]')?.focus();
    try {
      state.service = await call("status");
      const active = await call("active");
      if (active.id) await loadRun(active.id);
      else {
        const ctx = context();
        if (ctx.repo && ctx.issue) {
          const recent = (await call("list")).runs.find(r => r.mode === "github" && r.repo.toLowerCase() === ctx.repo.toLowerCase()
            && r.issue === ctx.issue && r.status === "awaiting_approval");
          if (recent) {await call("active", {id: recent.id}); await loadRun(recent.id);}
        }
      }
    } catch(error) { state.error = error.message; }
    render();
  }
  async function start(mode) {
    const ctx = context();
    if (mode === "github" && !ctx.issue) throw new Error("Open a GitHub issue before starting Forge.");
    const run = await call("create", {body: {mode, repo: ctx.repo || "forge-demo/sample-api", issue: ctx.issue || 42, request_key: crypto.randomUUID()}});
    state.history = null; state.tab = "progress"; state.confirm = false;
    await call("active", {id: run.id}); await loadRun(run.id);
  }
  async function act(action) {
    if (action === "open") return open();
    if (action === "close") {state.open = false; clearTimeout(timer); render(); root.querySelector(".launcher")?.focus(); return;}
    if (action === "options") return call("options");
    if (action === "dismiss") {state.error = ""; return;}
    if (action === "demo" || action === "start") return start(action === "demo" ? "demo" : "github");
    if (action === "history") {state.history = (await call("list")).runs; return;}
    if (action === "back") {state.history = null; return;}
    if (action === "new") {state.run = null; state.history = null; state.confirm = false; await call("active", {id: null}); return;}
    if (action === "review-approve") {state.tab = "changes"; state.confirm = true; return;}
    if (action === "revision") {state.revision = !state.revision; return;}
    if (action === "submit-revision") {
      const feedback = root.querySelector("#forge-feedback")?.value.trim() || "";
      if (feedback.length < 10) throw new Error("Describe the requested change in at least 10 characters.");
      const next = await call("revision", {id: state.run.id, body: {feedback, request_key: crypto.randomUUID()}});
      state.revision = false; state.confirm = false; state.tab = "progress";
      await call("active", {id: next.id}); return loadRun(next.id);
    }
    if (action === "refresh") {
      const next = await call("revision", {id: state.run.id, body: {feedback: "Refresh this proposal against the current base and rerun all required checks before human approval.", request_key: crypto.randomUUID()}});
      state.revision = false; state.confirm = false; state.tab = "progress";
      await call("active", {id: next.id}); return loadRun(next.id);
    }
    if (action === "approve") {
      const demo = state.run.mode === "demo";
      const consent = root.querySelector("#forge-ci-consent")?.checked === true;
      if (!demo && !consent) throw new Error("Review the diff and checks, then acknowledge the publishing action.");
      await call("approve", {id: state.run.id, body: {fingerprint: state.run.candidate.fingerprint, publish_consent: consent}});
      state.confirm = false; return loadRun(state.run.id);
    }
    if (action === "cancel" || action === "reject") {await call(action, {id: state.run.id}); return loadRun(state.run.id);}
    if (action === "download") {
      const data = await call("patch", {id: state.run.id});
      const url = URL.createObjectURL(new Blob([data.text], {type: "text/plain"}));
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = `forge-${state.run.id.slice(0, 8)}.patch`; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
  root.addEventListener("click", async event => {
    const el = event.target.closest("button");
    if (!el || !event.isTrusted || el.disabled || state.busy) return;
    if (el.dataset.tab) {state.tab = el.dataset.tab; render(); root.querySelector(`[data-tab="${state.tab}"]`)?.focus(); return;}
    if (el.dataset.file) {state.selectedFile = Number(el.dataset.file); render(); return;}
    if (el.dataset.run) {
      state.history = null; state.tab = "progress"; await call("active", {id: el.dataset.run});
      try {await loadRun(el.dataset.run);} catch(error) {state.error = error.message; render();} return;
    }
    const action = el.dataset.action; if (!action) return;
    state.error = ""; state.busy = true;
    try {await act(action);} catch(error) {state.error = error.message;}
    finally {state.busy = false; render();}
  });
  root.addEventListener("keydown", event => {
    if (event.key === "Escape") {state.open = false; clearTimeout(timer); render(); root.querySelector(".launcher")?.focus();}
    if (event.target.dataset?.tab && ["ArrowLeft", "ArrowRight"].includes(event.key)) {
      event.preventDefault(); const tabs = ["progress", "changes", "checks"];
      state.tab = tabs[(tabs.indexOf(state.tab) + (event.key === "ArrowRight" ? 1 : 2)) % 3];
      render(); root.querySelector(`[data-tab="${state.tab}"]`)?.focus();
    }
  });
  new MutationObserver(theme).observe(document.documentElement, {attributes: true, attributeFilter: ["data-color-mode", "data-dark-theme"]});
  setInterval(() => {
    if (location.pathname !== state.route) {
      state.route = location.pathname; state.run = null; state.history = null; state.confirm = false;
      clearTimeout(timer); call("active", {id: null}).catch(() => {}); render();
    }
  }, 1200);
  render();
})();
