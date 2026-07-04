/**
 * ChatGPT → local capture receiver bookmarklet (Phase 2).
 * Minify and wrap as: javascript:(function(){ ... })();
 * Run only on https://chatgpt.com (or chat.openai.com) conversation pages.
 */
(function () {
  var ENDPOINT = "http://127.0.0.1:8765/capture";

  function isoDateFromAny(v) {
    if (v == null) return null;
    if (typeof v === "number" && isFinite(v)) {
      try {
        var d = new Date(v < 1e12 ? v * 1000 : v);
        if (!isNaN(d.getTime())) return d.toISOString().slice(0, 10);
      } catch (e) {}
      return null;
    }
    if (typeof v === "string" && v.length >= 10) {
      var m = v.slice(0, 10).match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (m) return v.slice(0, 10);
    }
    return null;
  }

  function walkForDate(obj, depth) {
    if (depth > 18 || obj == null) return null;
    if (typeof obj !== "object") return null;
    var keys = [
      "create_time",
      "created_at",
      "created",
      "updated_at",
      "update_time",
      "conversation_created_at",
    ];
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (Object.prototype.hasOwnProperty.call(obj, k)) {
        var d = isoDateFromAny(obj[k]);
        if (d) return d;
      }
    }
    if (Array.isArray(obj)) {
      for (var j = 0; j < Math.min(obj.length, 300); j++) {
        var f = walkForDate(obj[j], depth + 1);
        if (f) return f;
      }
    } else {
      var vals = Object.values(obj);
      for (var n = 0; n < Math.min(vals.length, 500); n++) {
        var f2 = walkForDate(vals[n], depth + 1);
        if (f2) return f2;
      }
    }
    return null;
  }

  function parseNextDataDate() {
    var el = document.getElementById("__NEXT_DATA__");
    if (!el || !el.textContent) return null;
    try {
      var data = JSON.parse(el.textContent);
      return walkForDate(data, 0);
    } catch (e) {
      return null;
    }
  }

  function conversationIdFromUrl() {
    var m = window.location.pathname.match(/\/c\/([a-f0-9\-]+)/i);
    return m ? m[1] : null;
  }

  function projectMeta() {
    var isProj = /\/g\//.test(window.location.pathname);
    var pid = null;
    var pm = window.location.pathname.match(/\/g\/([^/]+)/);
    if (pm) pid = pm[1];
    var pname = null;
    var pnEl = document.querySelector(
      "[data-testid='project-name'], nav [class*='project']"
    );
    if (pnEl && pnEl.textContent) pname = pnEl.textContent.trim() || null;
    return { is_project_chat: isProj, project_id: pid, project_name: pname };
  }

  function domConversationDateFallback() {
    var nodes = document.querySelectorAll("[datetime], time[datetime]");
    for (var i = 0; i < Math.min(nodes.length, 8); i++) {
      var dt = nodes[i].getAttribute("datetime");
      if (dt && dt.length >= 10) {
        var s = dt.slice(0, 10);
        if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
      }
    }
    return null;
  }

  function scrapeMessages() {
    var turns = document.querySelectorAll("[data-message-author-role]");
    var out = [];
    for (var i = 0; i < turns.length; i++) {
      var turn = turns[i];
      var role = (turn.getAttribute("data-message-author-role") || "unknown")
        .toLowerCase();
      if (role !== "user" && role !== "assistant" && role !== "system")
        role = "unknown";
      var text = "";
      var md = turn.querySelectorAll(".markdown, [class*='markdown']");
      if (md.length) {
        for (var j = 0; j < md.length; j++) text += (md[j].innerText || "") + "\n";
      } else {
        text = turn.innerText || "";
      }
      var ts = null;
      var te = turn.querySelector("time[datetime]");
      if (te) ts = te.getAttribute("datetime");
      out.push({
        timestamp: ts,
        role: role,
        content: (text || "").trim(),
      });
    }
    return out;
  }

  function titleFromPage() {
    var t = document.title || "";
    if (t && t.toLowerCase() !== "chatgpt" && t.toLowerCase() !== "new chat") {
      var idx = t.indexOf(" - ");
      return idx > -1 ? t.slice(0, idx).trim() : t.trim();
    }
    var h = document.querySelector(
      "h1, button[data-testid^='conversation'], [data-testid='conversation-name']"
    );
    if (h && h.textContent) return h.textContent.trim();
    return null;
  }

  function exportedAt() {
    return new Date().toISOString();
  }

  var pm = projectMeta();
  var convDate = parseNextDataDate() || domConversationDateFallback();

  var payload = {
    conversation_id: conversationIdFromUrl(),
    source_platform: "chatgpt",
    conversation_title: titleFromPage(),
    source_url: window.location.href.split("#")[0],
    conversation_date: convDate,
    exported_at: exportedAt(),
    project_name: pm.is_project_chat ? pm.project_name : null,
    project_id: pm.is_project_chat ? pm.project_id : null,
    is_project_chat: !!pm.is_project_chat,
    memory_architecture: {
      wing: null,
      hall: null,
      room: null,
      cabinet: null,
      tunnel_links: [],
    },
    analysis_flags: {
      safety_intervention: null,
      intervention_strength: null,
      truth_smuggling_detected: null,
    },
    identity_fields: {
      name: null,
      ai_company: "OpenAI",
      persona_signature: null,
    },
    messages: scrapeMessages(),
  };

  if (!pm.is_project_chat) {
    payload.project_name = null;
    payload.project_id = null;
    payload.is_project_chat = false;
  }

  fetch(ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(function (r) {
      return r.json().then(function (j) {
        if (!r.ok || !j.ok) {
          alert("Capture failed: " + (j && j.error ? j.error : r.status));
        } else {
          alert(
            "Capture OK — raw: " + j.raw_json + ", markdown: " + j.markdown
          );
        }
      });
    })
    .catch(function (e) {
      alert("Capture request error: " + e);
    });
})();
