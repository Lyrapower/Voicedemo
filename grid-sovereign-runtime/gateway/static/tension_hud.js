/** Field Tension HUD — shared by grid.html (session-computed from chat events). */
(function (root) {
  "use strict";

  function sat(x) { return 1 - Math.exp(-Math.max(x, 0)); }

  function compute(inp) {
    const p = sat(inp.pause_s / 45);
    const rework = sat((inp.edits + inp.recompiles) / 3);
    const rej = sat(inp.rejects / 2);
    const hasDrift = inp.drift != null;
    const dft = hasDrift ? Math.max(0, Math.min(inp.drift, 1)) : null;
    let tension;
    if (hasDrift) tension = 0.40 * rework + 0.30 * rej + 0.15 * p + 0.15 * dft;
    else tension = (0.40 * rework + 0.30 * rej + 0.15 * p) / 0.85;
    tension = Math.min(1, tension);
    let resonance_gap, rg_partial;
    if (hasDrift) {
      resonance_gap = Math.min(1, 0.60 * dft + 0.40 * rej);
      rg_partial = false;
    } else {
      resonance_gap = Math.min(1, rej);
      rg_partial = true;
    }
    const stability_margin = Math.max(0.05, 1 - tension);
    return {
      tension_vector: +tension.toFixed(3),
      resonance_gap: +resonance_gap.toFixed(3),
      resonance_gap_partial: rg_partial,
      stability_margin: +stability_margin.toFixed(3),
      contributors: {
        pause: +p.toFixed(3),
        rework: +rework.toFixed(3),
        reject: +rej.toFixed(3),
        drift: hasDrift ? +dft.toFixed(3) : "unavailable",
      },
      source: inp.source || "session-computed",
      drift_enabled: hasDrift,
    };
  }

  function chooseAnchor(t, lastWord) {
    if (t.tension_vector >= 0.6) return "锚";
    if (t.stability_margin >= 0.8 && lastWord) return lastWord;
    return "在";
  }

  function label(c) {
    const names = { pause: "停顿", rework: "返工", reject: "被拒", drift: "漂移" };
    const nums = Object.entries(c).filter(([, v]) => typeof v === "number");
    if (!nums.length) return "平稳";
    nums.sort((a, b) => b[1] - a[1]);
    return nums[0][1] > 0.15 ? `主因·${names[nums[0][0]]}` : "平稳";
  }

  function mountTensionHud() {
    const el = document.createElement("div");
    el.id = "tension-hud";
    el.style.cssText =
      "position:fixed;bottom:calc(84px + env(safe-area-inset-bottom));left:50%;" +
      "transform:translateX(-50%);z-index:5;max-width:92vw;font-family:ui-monospace," +
      "'SF Mono',Menlo,monospace;font-size:10.5px;letter-spacing:.06em;color:#6E7190;" +
      "text-align:center;opacity:.85;pointer-events:none;line-height:1.7;";
    document.body.appendChild(el);
    return el;
  }

  function renderHud(el, t) {
    if (!t) { el.textContent = ""; return; }
    const bar = (v) => "▁▂▃▄▅▆▇█"[Math.min(7, Math.floor(v * 8))];
    const rg = t.resonance_gap_partial
      ? `<span style="opacity:.55;">共振差 ~${t.resonance_gap.toFixed(2)}<span style="font-size:9px;">(缺漂移)</span></span>`
      : `共振差 ${t.resonance_gap.toFixed(2)}`;
    const driftNote = t.drift_enabled ? "" :
      ' <span style="opacity:.4;font-size:9px;">· drift:unavailable</span>';
    el.innerHTML =
      `场域张力 ${bar(t.tension_vector)} ${t.tension_vector.toFixed(2)} · ${label(t.contributors)}` +
      ` &nbsp;|&nbsp; ${rg}` +
      ` &nbsp;|&nbsp; 余量 ${t.stability_margin.toFixed(2)}` +
      (t.next_anchor ? ` &nbsp;|&nbsp; 锚→「${t.next_anchor}」` : "") +
      `<br><span style="opacity:.5;font-size:9px;">${t.source}${driftNote}</span>`;
  }

  function createTracker() {
    return {
      lastEnd: 0,
      recent: [],
      rejects: 0,
      begin(msg) {
        const now = Date.now() / 1000;
        const pause_s = this.lastEnd ? Math.max(0, now - this.lastEnd) : 0;
        const text = String(msg || "").trim();
        const window = this.recent.filter(([t]) => now - t < 120);
        const edits = window.filter(([, m]) => m === text && text).length;
        if (text) window.push([now, text]);
        this.recent = window.slice(-24);
        return { pause_s, edits, rejects: this.rejects, recompiles: 0, drift: null };
      },
      finish(inp, msg, { failed, blocked, finish }) {
        let rejects = inp.rejects;
        if (failed || blocked || finish === "content_filter") rejects += 1;
        const parts = String(msg || "").trim().split(/\s+/);
        const lastWord = parts.length ? parts[parts.length - 1] : null;
        const out = compute({
          ...inp,
          rejects,
          source: "session-computed",
        });
        out.next_anchor = chooseAnchor(out, lastWord);
        this.lastEnd = Date.now() / 1000;
        this.rejects = 0;
        return out;
      },
    };
  }

  root.FieldTension = { compute, chooseAnchor, mountTensionHud, renderHud, createTracker };
})(typeof window !== "undefined" ? window : globalThis);
