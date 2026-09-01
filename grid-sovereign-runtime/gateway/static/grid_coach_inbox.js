"use strict";
/** Coach Inbox UI — COACH INBOX UI SPEC v1 (2026-07-17) */
window.CoachInbox = (function () {
  const PAGE = 20;
  const POLL_MS = 30000;
  const CONFIRM_MS = 3000;
  const EST_COST = 0.21;

  let cfg = {};
  let filter = "pending";
  let offset = 0;
  let total = 0;
  let rows = [];
  let budget = {};
  let counts = {};
  let selectedId = null;
  let detail = null;
  let pollTimer = null;
  let confirmTimer = null;
  let pendingAction = null;
  let composeConfirm = false;

  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");

  function fmtCost(v) {
    if (v == null || Number.isNaN(Number(v))) return "—";
    return "$" + Number(v).toFixed(2);
  }

  function fmtTime(ts) {
    if (!ts) return "—";
    try {
      const d = new Date(ts);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch (e) {
      return String(ts).slice(11, 16) || "—";
    }
  }

  function trunc(s, n) {
    s = String(s || "");
    return s.length <= n ? s : s.slice(0, n - 1) + "…";
  }

  function statusDot(st, skip) {
    if (skip) return "skip";
    return st || "pending";
  }

  async function api(path, opts) {
    const r = await fetch(cfg.storeBase() + path, {
      ...opts,
      headers: { ...(opts && opts.body ? { "Content-Type": "application/json" } : {}), ...cfg.storeHdrs() },
    });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
    return j;
  }

  function toast(msg, ok) {
    const el = $("#cinToast");
    if (!el) return;
    el.textContent = msg;
    el.className = "cin-toast" + (ok ? " ok" : " err");
    el.classList.remove("hidden");
    clearTimeout(el._t);
    el._t = setTimeout(() => el.classList.add("hidden"), 4000);
  }

  function showView(name) {
    for (const v of ["cinListView", "cinDetailView", "cinComposeView"]) {
      const el = $("#" + v);
      if (el) el.classList.toggle("hidden", v !== name);
    }
  }

  function renderBudget() {
    const el = $("#cinBudget");
    if (!el || !budget) return;
    let line =
      "calls " +
      (budget.calls ?? 0) +
      "/" +
      (budget.daily_cap ?? "?") +
      " · " +
      fmtCost(budget.estimated_cost_usd) +
      " · skips " +
      (budget.skips ?? 0);
    if (budget.at_cap) line += " · cap reached";
    el.textContent = line;
    el.classList.toggle("amber", !!budget.at_cap);
  }

  function renderChips() {
    const el = $("#cinChips");
    if (!el) return;
    const chips = [
      ["all", "All"],
      ["pending", "Pending"],
      ["held", "Held"],
      ["approved", "Approved"],
      ["rejected", "Rejected"],
    ];
    el.innerHTML = chips
      .map(
        ([k, label]) =>
          `<button type="button" class="cin-chip${filter === k ? " on" : ""}" data-f="${k}">${label} (${counts[k] ?? 0})</button>`,
      )
      .join("");
    el.querySelectorAll(".cin-chip").forEach((b) => {
      b.onclick = () => {
        filter = b.dataset.f;
        offset = 0;
        void loadList();
      };
    });
  }

  function renderRows() {
    const el = $("#cinRows");
    if (!el) return;
    if (!rows.length) {
      el.innerHTML =
        `<p class="cin-empty">No ${filter === "all" ? "" : filter + " "}records. Auto-coach fires after each GRID compile. <button type="button" class="cin-link" id="cinEmptyManual">Manual submit</button></p>`;
      const m = $("#cinEmptyManual");
      if (m) m.onclick = () => showCompose();
      return;
    }
    el.innerHTML = rows
      .map((r) => {
        const dot = statusDot(r.status, r.skip_reason);
        const fail = r.skip_reason
          ? `<span class="cin-skip">skipped: ${esc(r.skip_reason)}</span>`
          : esc(trunc(r.failure_type || r.preview, 22));
        return (
          `<button type="button" class="cin-row" data-id="${esc(r.record_id)}">` +
          `<span class="cin-row-l1"><span class="cin-dot ${dot}">●</span> ${fmtTime(r.compile_ts)} <span class="cin-node">${esc(trunc(r.node_id, 14))}</span> ${fail}</span>` +
          `<span class="cin-row-l2">${fmtCost(r.cost_usd)} · ${esc(r.status || "pending")}</span>` +
          `</button>`
        );
      })
      .join("");
    el.querySelectorAll(".cin-row").forEach((b) => {
      b.onclick = () => void openDetail(b.dataset.id);
    });
    const more = $("#cinLoadMore");
    if (more) more.classList.toggle("hidden", offset + rows.length >= total);
  }

  async function loadList(append) {
    try {
      const j = await api(
        `/store/distill/inbox?filter=${encodeURIComponent(filter)}&limit=${PAGE}&offset=${append ? offset : 0}`,
      );
      budget = j.budget || {};
      counts = j.counts || {};
      total = j.total ?? 0;
      if (append) {
        rows = rows.concat(j.rows || []);
        offset = rows.length;
      } else {
        rows = j.rows || [];
        offset = rows.length;
      }
      renderBudget();
      renderChips();
      renderRows();
    } catch (e) {
      toast("list failed · " + e.message, false);
    }
  }

  function card(label, body, cls) {
    return `<section class="cin-card${cls ? " " + cls : ""}"><div class="cin-card-lbl">${label}</div><div class="cin-card-body">${body}</div></section>`;
  }

  function renderDetail() {
    const body = $("#cinDetailBody");
    const title = $("#cinDetailTitle");
    if (!body || !detail) return;
    if (title) title.textContent = trunc(detail.failure_type || detail.record_id, 28);

    const meta = detail.cli_meta || {};
    const coach = detail.coach && typeof detail.coach === "object" ? detail.coach : null;
    const skip = !!detail.skip_reason && !coach;

    let draft = esc(detail.student_draft || "");
    try {
      const p = JSON.parse(detail.student_draft || "");
      draft = `<pre class="cin-json">${esc(JSON.stringify(p, null, 2))}</pre>`;
    } catch (e) {
      draft = `<pre class="cin-pre">${draft}</pre>`;
    }

    let coachHtml = "";
    if (skip) {
      coachHtml = card("FABLE COACH", `<p class="cin-skip">no coach output · ${esc(detail.skip_reason)}</p>`, "cin-coach");
    } else if (coach) {
      const mc = coach.method_card || {};
      const pp = coach.preference_pair || {};
      let vocab = "";
      if (detail.vocab_violation) {
        vocab = `<div class="cin-vocab">held: ${esc(detail.vocab_violation)}</div>`;
      }
      coachHtml = card(
        "FABLE COACH",
        vocab +
          `<span class="cin-chip-ft">${esc(coach.failure_type || "—")}</span>` +
          (coach.missing_boundary ? `<p><b>boundary</b> ${esc(coach.missing_boundary)}</p>` : "") +
          (coach.better_move ? `<p><b>better_move</b> ${esc(coach.better_move)}</p>` : "") +
          (coach.minimal_correction
            ? `<div class="cin-amber-block"><div class="cin-amber-cap">example output — not validated against system vocab</div><pre>${esc(JSON.stringify(coach.minimal_correction, null, 2))}</pre></div>`
            : "") +
          `<details class="cin-fold"><summary>method_card</summary>` +
          `<p>trigger: ${esc(mc.trigger)}</p><p>move: ${esc(mc.move)}</p><p>verifier: ${esc(mc.verifier_rule)}</p></details>` +
          `<details class="cin-fold"><summary>preference_pair</summary>` +
          `<p>rejected: ${esc(pp.rejected_reason)}</p><p>chosen: ${esc(pp.chosen_shape)}</p></details>` +
          `<div class="cin-cost-foot">claude-fable-5 · ${fmtCost(meta.cost_usd ?? detail.cost_usd)} · ${meta.duration_ms ? (meta.duration_ms / 1000).toFixed(1) + "s" : "—"} · run ${esc(trunc(detail.run_id, 12))}</div>`,
        "cin-coach",
      );
    }

    const hist = (detail.decisions || [])
      .slice()
      .reverse()
      .map(
        (d) =>
          `v${d.review_version ?? "?"}  ${d.status}  ${d.decided_by || "—"}  ${String(d.decided_at || "").slice(5, 16)}  "${esc(d.reason || "")}"`,
      )
      .join("\n");

    body.innerHTML =
      card(
        "IDENTITY",
        `<code class="cin-mono">${esc(trunc(detail.record_id, 12))} <button type="button" class="cin-copy" data-copy="${esc(detail.record_id)}">copy</button> · ${esc(detail.compile_ts)} · ${esc(detail.node_id)} · ${esc(detail.task)} · ${esc(detail.client)}</code>`,
      ) +
      card("INSTRUCTION", `<pre class="cin-pre">${esc(detail.instruction || "")}</pre>`) +
      card("DRAFT · demo/aster", draft) +
      coachHtml +
      card("DECISIONS", hist ? `<pre class="cin-pre">${hist}</pre>` : `<p class="cin-muted">no decisions — pending</p>`);

    body.querySelectorAll(".cin-copy").forEach((b) => {
      b.onclick = () => {
        void navigator.clipboard.writeText(b.dataset.copy || "");
        toast("copied", true);
      };
    });

    renderActions(skip);
  }

  function renderActions(skip) {
    const bar = $("#cinActions");
    if (!bar || !detail) return;
    const st = detail.status || "pending";
    bar.innerHTML =
      `<div class="cin-actions-inner">` +
      `<span class="cin-cur-st">${esc(st)}</span>` +
      `<button type="button" class="cin-act approve" data-act="approved"${skip ? " disabled title='no coach output'" : ""}>Approve</button>` +
      `<button type="button" class="cin-act reject" data-act="rejected"${skip ? " disabled" : ""}>Reject</button>` +
      `<button type="button" class="cin-act hold" data-act="held"${skip ? " disabled" : ""}>Hold</button>` +
      `</div>` +
      `<div id="cinReasonWrap" class="cin-reason hidden">` +
      `<input id="cinReason" placeholder="reason" />` +
      `<button type="button" id="cinReasonGo">Confirm</button>` +
      `<button type="button" id="cinReasonCancel">Cancel</button>` +
      `</div>` +
      (skip ? `<p class="cin-muted">no coach output — actions disabled</p>` : "");

    bar.querySelectorAll(".cin-act").forEach((b) => {
      b.onclick = () => startAction(b.dataset.act);
    });
    const cancel = $("#cinReasonCancel");
    if (cancel) cancel.onclick = () => {
      pendingAction = null;
      $("#cinReasonWrap").classList.add("hidden");
    };
    const go = $("#cinReasonGo");
    if (go) go.onclick = () => void commitAction();
  }

  function startAction(act) {
    pendingAction = act;
    const wrap = $("#cinReasonWrap");
    const inp = $("#cinReason");
    if (!wrap || !inp) return;
    wrap.classList.remove("hidden");
    inp.placeholder = act === "approved" ? "reason (optional)" : "reason (required)";
    inp.value = "";
    inp.focus();
  }

  async function commitAction() {
    if (!pendingAction || !detail) return;
    const reason = ($("#cinReason") && $("#cinReason").value.trim()) || "";
    if (pendingAction !== "approved" && !reason) {
      toast("reason required", false);
      return;
    }
    const rid = detail.record_id;
    const prev = detail.status;
    detail.status = pendingAction;
    renderActions(!!detail.skip_reason && !detail.coach);
    try {
      const j = await api("/store/distill/review", {
        method: "POST",
        body: JSON.stringify({ record_id: rid, status: pendingAction, reason, via: "coach-inbox" }),
      });
      detail.status = j.current_status || pendingAction;
      detail.decisions = (detail.decisions || []).concat([j.decision]);
      renderDetail();
      toast("saved · " + detail.status, true);
      void loadList();
    } catch (e) {
      detail.status = prev;
      renderDetail();
      toast(String(e.message), false);
    }
    pendingAction = null;
    $("#cinReasonWrap").classList.add("hidden");
  }

  async function openDetail(id) {
    try {
      detail = await api("/store/distill/record/" + encodeURIComponent(id));
      selectedId = id;
      showView("cinDetailView");
      renderDetail();
    } catch (e) {
      toast("detail failed · " + e.message, false);
    }
  }

  function showCompose() {
    showView("cinComposeView");
    const btn = $("#cinSend");
    if (btn) {
      btn.textContent = budget.at_cap ? "Save without coach" : "送 Fable coach";
      btn.dataset.confirm = "";
    }
    composeConfirm = false;
  }

  async function loadComposeDraft() {
    try {
      const j = await api("/store/distill/latest_compile");
      $("#cinIns").value = j.instruction || "";
      $("#cinDraft").value = j.draft || "";
      toast("loaded compile", true);
    } catch (e) {
      toast("load failed · " + e.message, false);
    }
  }

  async function submitCompose() {
    const instruction = ($("#cinIns") && $("#cinIns").value.trim()) || "";
    const draft = ($("#cinDraft") && $("#cinDraft").value.trim()) || "";
    if (!draft) {
      toast("draft required", false);
      return;
    }
    const btn = $("#cinSend");
    const atCap = !!budget.at_cap;

    if (!atCap && !composeConfirm) {
      composeConfirm = true;
      btn.textContent = `Confirm · ~$${EST_COST.toFixed(2)} · 1 call`;
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(() => {
        composeConfirm = false;
        btn.textContent = "送 Fable coach";
      }, CONFIRM_MS);
      return;
    }

    composeConfirm = false;
    btn.disabled = true;
    btn.textContent = atCap ? "saving…" : "coaching… ~30s";
    try {
      const task = cfg.classifyTask(instruction || draft);
      const j = await api("/store/field/coach", {
        method: "POST",
        body: JSON.stringify({
          instruction: instruction || draft,
          draft,
          task,
          sync: true,
          client: "app",
          persona: "GRID-coach",
          force: !atCap,
        }),
      });
      const rid = (j.record && j.record.record_id) || j.record_id;
      btn.disabled = false;
      btn.textContent = atCap ? "Save without coach" : "送 Fable coach";
      if (rid) {
        await loadList();
        await openDetail(rid);
      } else {
        toast(atCap ? "saved skip record" : "done", true);
        showView("cinListView");
        void loadList();
      }
    } catch (e) {
      btn.disabled = false;
      btn.textContent = atCap ? "Save without coach" : "送 Fable coach";
      toast(String(e.message), false);
    }
  }

  function bind() {
    const manual = $("#cinManual");
    if (manual) manual.onclick = () => showCompose();
    const back = $("#cinBack");
    if (back) back.onclick = () => {
      showView("cinListView");
      void loadList();
    };
    const composeBack = $("#cinComposeBack");
    if (composeBack) composeBack.onclick = () => showView("cinListView");
    const loadBtn = $("#cinLoadCompile");
    if (loadBtn) loadBtn.onclick = () => void loadComposeDraft();
    const sendBtn = $("#cinSend");
    if (sendBtn) sendBtn.onclick = () => void submitCompose();
    const more = $("#cinLoadMore");
    if (more) more.onclick = () => void loadList(true);
  }

  function startPoll() {
    stopPoll();
    void loadList();
    pollTimer = setInterval(() => {
      if (document.hidden) return;
      if ($("#cinListView") && !$("#cinListView").classList.contains("hidden")) void loadList();
    }, POLL_MS);
  }

  function stopPoll() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  return {
    init(c) {
      cfg = c;
      bind();
    },
    onShow() {
      showView("cinListView");
      startPoll();
    },
    onHide() {
      stopPoll();
    },
  };
})();
