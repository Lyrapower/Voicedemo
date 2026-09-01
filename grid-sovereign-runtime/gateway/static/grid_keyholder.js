/* Keyholder challenge-response — client HMAC only; raw key never leaves device. */
(function (global) {
  "use strict";

  const KEY_BYTES = "voice_kh_key_bytes";
  const KEY_REF = "voice_keyholder";

  function validateKeyHex(hex) {
    const h = String(hex || "").replace(/\s+/g, "");
    if (!/^[0-9a-fA-F]+$/.test(h)) throw new Error("key 须为 hex");
    return h;
  }

  /** Match gateway keyholder.key: ASCII hex text bytes, not decoded binary. */
  function keyMaterialFromHex(hex) {
    return new TextEncoder().encode(validateKeyHex(hex));
  }

  function hasKey() {
    try {
      const ref = JSON.parse(localStorage.getItem(KEY_REF) || "null");
      return !!(ref && ref.configured && localStorage.getItem(KEY_BYTES));
    } catch (e) {
      return false;
    }
  }

  function keyRef() {
    try {
      return JSON.parse(localStorage.getItem(KEY_REF) || "null");
    } catch (e) {
      return null;
    }
  }

  function saveKeyHex(hex) {
    const h = validateKeyHex(hex);
    localStorage.setItem(KEY_BYTES, h);
    localStorage.setItem(
      KEY_REF,
      JSON.stringify({
        configured: true,
        key_ref: "device-local-v1",
        saved_at: Date.now(),
      })
    );
  }

  function clearKey() {
    localStorage.removeItem(KEY_BYTES);
    localStorage.removeItem(KEY_REF);
  }

  async function hmacResponse(keyBytes, nonce, ts) {
    const msg = `${nonce}|${Math.trunc(Number(ts))}`;
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      keyBytes,
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const sig = await crypto.subtle.sign("HMAC", cryptoKey, new TextEncoder().encode(msg));
    return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function signChallenge(baseUrl) {
    const raw = localStorage.getItem(KEY_BYTES);
    if (!raw) throw new Error("keyholder: 需先配置钥匙");
    const keyBytes = keyMaterialFromHex(raw);
    const ch = await fetch(baseUrl.replace(/\/$/, "") + "/challenge/new", {
      method: "POST",
    }).then((r) => {
      if (!r.ok) throw new Error("challenge/new failed");
      return r.json();
    });
    const response = await hmacResponse(keyBytes, ch.nonce, ch.ts);
    return { keyholder: { nonce: ch.nonce, ts: ch.ts, response } };
  }

  global.GridKeyholder = {
    hasKey,
    keyRef,
    saveKeyHex,
    clearKey,
    signChallenge,
  };
})(typeof window !== "undefined" ? window : globalThis);
