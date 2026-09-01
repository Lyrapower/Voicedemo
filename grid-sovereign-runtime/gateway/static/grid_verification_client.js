/* Shared Grid verification client — browser only. Requires GridKeyholder (grid_keyholder.js).
   Headless services MUST use grid_verification_client.py (delegated service signer). */
(function (global) {
  "use strict";

  const SCHEMA = "grid-chain-v1";
  const BROWSER_SIGNER = "keyholder-v1";

  function sortKeysDeep(v) {
    if (Array.isArray(v)) return v.map(sortKeysDeep);
    if (v && typeof v === "object") {
      return Object.keys(v)
        .sort()
        .reduce((o, k) => {
          o[k] = sortKeysDeep(v[k]);
          return o;
        }, {});
    }
    return v;
  }

  async function sha256Hex(text) {
    const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  function normalizeMessagesForHash(messages) {
    return (messages || []).map((m) => {
      if (!m || typeof m !== "object") return { role: m && m.role, content: "" };
      let content = m.content;
      if (content == null) content = "";
      else if (typeof content !== "string" && !Array.isArray(content)) content = String(content);
      return { role: m.role, content };
    });
  }

  async function canonicalPayloadHash(body) {
    const subset = {
      model: body.model,
      messages: normalizeMessagesForHash(body.messages),
    };
    const canonical = JSON.stringify(sortKeysDeep(subset));
    return sha256Hex(canonical);
  }

  function gatewayRoot(gwOrBase) {
    return String(gwOrBase || "")
      .replace(/\/v1\/?$/i, "")
      .replace(/\/+$/,"");
  }

  async function buildForChatBody(chatBody, gwOrBase) {
    if (!global.GridKeyholder || !GridKeyholder.hasKey()) {
      throw new Error("keyholder: 需先配置钥匙 — Grid 链路验证拒绝注入");
    }
    const base = gatewayRoot(gwOrBase);
    const normalized = Object.assign({}, chatBody, {
      messages: normalizeMessagesForHash(chatBody.messages),
    });
    const route_id = crypto.randomUUID();
    const payload_hash = await canonicalPayloadHash(normalized);
    const seal = await fetch(base + "/grid/verification/trace-seal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ route_id, payload_hash, chat_body: normalized }),
    });
    if (!seal.ok) {
      const detail = await seal.text();
      throw new Error("trace-seal failed HTTP " + seal.status + ": " + detail.slice(0, 200));
    }
    const sealed = await seal.json();
    const khWrap = await GridKeyholder.signChallenge(base);
    return {
      grid_verification: {
        schema_version: SCHEMA,
        route_id,
        signer_id: BROWSER_SIGNER,
        payload_hash,
        keyholder: khWrap.keyholder,
        trace: sealed.trace,
      },
    };
  }

  async function attachToChatBody(chatBody, gwOrBase) {
    const normalized = Object.assign({}, chatBody, {
      messages: normalizeMessagesForHash(chatBody.messages),
    });
    const bundle = await buildForChatBody(normalized, gwOrBase);
    return Object.assign({}, normalized, bundle);
  }

  function isAsterChatBody(body) {
    const m = String((body && body.model) || "").trim();
    return m === "demo/aster" || m.endsWith("/aster");
  }

  global.GridVerificationClient = {
    SCHEMA,
    BROWSER_SIGNER,
    normalizeMessagesForHash,
    canonicalPayloadHash,
    buildForChatBody,
    attachToChatBody,
    isAsterChatBody,
  };
})(typeof window !== "undefined" ? window : globalThis);
