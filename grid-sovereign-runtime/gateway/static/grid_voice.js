/* Grid Voice v2 — Silero VAD + speechSynthesis + 回合状态机 (2026-07-20) */
(function (global) {
  "use strict";

  const MIC_RATE = 16000;
  const CH_MIC = 0x01;
  const CHUNK_MS = 20;
  const CHUNK_BYTES = ((MIC_RATE * CHUNK_MS) / 1000) * 2;
  const SENT_SPLIT = /([。！？!?…\n]+)/;
  const VAD_CDN = "https://cdn.jsdelivr.net/npm/@ricky0123/vad-web@0.0.22/dist/";
  const ORT_CDN = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/";

  function uuid4() {
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  function voiceWsUrl(gwV1) {
    const base = String(gwV1 || "").replace(/\/v1\/?$/i, "");
    const u = new URL(base || "http://127.0.0.1:8501", location.href);
    u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
    u.pathname = "/voice";
    u.search = "";
    u.hash = "";
    return u.toString();
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (document.querySelector(`script[src="${src}"]`)) {
        resolve();
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("script load failed: " + src));
      document.head.appendChild(s);
    });
  }

  async function loadSileroAssets() {
    await loadScript(ORT_CDN + "ort.min.js");
    await loadScript(VAD_CDN + "bundle.min.js");
    if (!global.vad || !global.vad.MicVAD) {
      throw new Error("vad-web not available");
    }
  }

  const KOKORO_URL = "http://127.0.0.1:8631/v1/audio/speech";
  const KOKORO_TIMEOUT_MS = 15000;
  const _HAS_CJK_RE = /[\u4e00-\u9fff\u3400-\u4dbf]/;

  function kokoroVoiceFor(text) {
    return _HAS_CJK_RE.test(text) ? "grid_zh" : "grid_en";
  }

  function kokoroAvailable() {
    if (typeof location === "undefined" || !location.hostname) return false;
    if (location.hostname.endsWith(".ts.net")) return false;
    return true;
  }

  class KokoroTtsQueue {
    constructor(hooks, ttsUrl) {
      this.hooks = hooks || {};
      this.ttsUrl = ttsUrl || KOKORO_URL;
      this.pending = "";
      this.queue = [];
      this.active = false;
      this._currentAudio = null;
    }
    feed(text) {
      this.pending += text || "";
      const parts = this.pending.split(SENT_SPLIT);
      if (parts.length < 2) return;
      let chunk = "";
      for (let i = 0; i < parts.length - 1; i += 2) {
        chunk = (parts[i] || "") + (parts[i + 1] || "");
        if (chunk.trim()) this.queue.push(chunk.trim());
      }
      this.pending = parts[parts.length - 1] || "";
      this._drain();
    }
    flush() {
      this.pending = "";
      this.queue = [];
      this.active = false;
      if (this._currentAudio) {
        try { this._currentAudio.pause(); } catch (e) {}
        this._currentAudio = null;
      }
    }
    flushPending() {
      const tail = (this.pending || "").trim();
      this.pending = "";
      if (tail) {
        this.queue.push(tail);
        this._drain();
      }
    }
    _drain() {
      if (this.active || !this.queue.length) return;
      this.active = true;
      const text = this.queue.shift();
      (async () => {
        try {
          if (this.hooks.onStart) this.hooks.onStart({ engine: "kokoro", text });
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), KOKORO_TIMEOUT_MS);
          const r = await fetch(this.ttsUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input: text, voice: kokoroVoiceFor(text), model: "kokoro" }),
            signal: controller.signal,
          });
          clearTimeout(timer);
          if (!r.ok) throw new Error("kokoro " + r.status);
          const blob = await r.blob();
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          this._currentAudio = audio;
          await new Promise((resolve, reject) => {
            audio.onended = () => { URL.revokeObjectURL(url); resolve(); };
            audio.onerror = () => { URL.revokeObjectURL(url); reject(new Error("audio play failed")); };
            audio.play().catch(reject);
          });
          if (this.hooks.onEnd) this.hooks.onEnd({ metrics: { engine: "kokoro" } });
        } catch (err) {
          console.warn("[GridVoice Kokoro TTS]", err);
          if (this.hooks.onEnd) this.hooks.onEnd({ metrics: { engine: "kokoro", error: String(err) } });
        } finally {
          this._currentAudio = null;
          this.active = false;
          if (this.queue.length) this._drain();
          else if (this.hooks.onIdle) this.hooks.onIdle();
        }
      })();
    }
  }

  class SpeechSynthQueue {
    constructor(hooks) {
      this.hooks = hooks || {};
      this.pending = "";
      this.queue = [];
      this.active = false;
      this.resumeTimer = null;
    }

    feed(text) {
      this.pending += text || "";
      const parts = this.pending.split(SENT_SPLIT);
      if (parts.length < 2) return;
      let chunk = "";
      for (let i = 0; i < parts.length - 1; i += 2) {
        chunk = (parts[i] || "") + (parts[i + 1] || "");
        if (chunk.trim()) this.queue.push(chunk.trim());
      }
      this.pending = parts[parts.length - 1] || "";
      this._drain();
    }

    flush() {
      if (this.resumeTimer) clearTimeout(this.resumeTimer);
      this.resumeTimer = null;
      this.pending = "";
      this.queue = [];
      this.active = false;
      try {
        speechSynthesis.cancel();
      } catch (e) {
        /* ignore */
      }
    }

    _drain() {
      if (this.active || !this.queue.length) return;
      if (!("speechSynthesis" in window)) return;
      this.active = true;
      if (this.hooks.onStart) this.hooks.onStart(this.queue[0]);
      const u = new SpeechSynthesisUtterance(this.queue.shift());
      u.lang = "zh-CN";
      u.onend = () => {
        this.active = false;
        if (this.hooks.onEnd) this.hooks.onEnd();
        if (this.queue.length) this._drain();
        else if (this.hooks.onIdle) this.hooks.onIdle();
      };
      u.onerror = () => {
        this.active = false;
        if (this.queue.length) this._drain();
      };
      speechSynthesis.speak(u);
    }

    flushPending() {
      const tail = (this.pending || "").trim();
      this.pending = "";
      if (tail) {
        this.queue.push(tail);
        this._drain();
      }
    }
  }

  async function signKeyholder(base) {
    if (!global.GridKeyholder || !GridKeyholder.hasKey()) {
      return {};
    }
    return GridKeyholder.signChallenge(base);
  }

  function configureVoiceAudioSession(mode) {
    const as = navigator.audioSession;
    if (!as || typeof as.type === "undefined") return false;
    try {
      as.type = mode;
      return true;
    } catch (e) {
      return false;
    }
  }

  function audioSessionStatusLine() {
    const as = navigator.audioSession;
    if (!as || typeof as.type === "undefined") {
      return "audioSession: unsupported";
    }
    return `audioSession: supported · type=${as.type}`;
  }

  class GridVoice {
    constructor(opts) {
      this.gwV1 = opts.gwV1;
      this.getHistory = opts.getHistory || (() => []);
      this.onAssistant = opts.onAssistant || (() => {});
      this.onSubtitle = opts.onSubtitle || (() => {});
      this.onTtsStart = opts.onTtsStart || (() => {});
      this.onTtsEnd = opts.onTtsEnd || (() => {});
      this.onAsr = opts.onAsr || (() => {});
      this.onAudioSession = opts.onAudioSession || (() => {});
      this.onDegrade = opts.onDegrade || (() => {});
      this.onState = opts.onState || (() => {});
      this.onError = opts.onError || (() => {});
      this.onTurnState = opts.onTurnState || (() => {});
      this.sessionId = uuid4();
      this.ws = null;
      this.turnState = "idle";
      this.micVad = null;
      const useKokoro = kokoroAvailable();
      this.tts = useKokoro
        ? new KokoroTtsQueue({
            onStart: (text) => this.onTtsStart({ engine: "kokoro", text }),
            onEnd: () => this.onTtsEnd({ metrics: { engine: "kokoro" } }),
            onIdle: () => this._afterSpeak(),
          })
        : new SpeechSynthQueue({
            onStart: (text) => this.onTtsStart({ engine: "speechSynthesis", text }),
            onEnd: () => this.onTtsEnd({ metrics: { engine: "speechSynthesis" } }),
            onIdle: () => this._afterSpeak(),
          });
      this._subtitle = "";
      this._pingTimer = null;
      this._enabled = false;
      this._lastEmotion = null;
      this._resumeTimer = null;
    }

    async toggle() {
      if (this._enabled) {
        await this.stop();
        return false;
      }
      await this.start();
      return true;
    }

    async start() {
      if (this._enabled) return;
      configureVoiceAudioSession("auto");
      await loadSileroAssets();
      await this._connectWs();
      this.micVad = await global.vad.MicVAD.new({
        onnxWASMBasePath: ORT_CDN,
        baseAssetPath: VAD_CDN,
        positiveSpeechThreshold: 0.6,
        negativeSpeechThreshold: 0.45,
        minSpeechFrames: 3,
        redemptionFrames: 12,
        preSpeechPadFrames: 1,
        onSpeechStart: () => this._onSpeechStart(),
        onSpeechEnd: (audio) => this._onSpeechEnd(audio),
        getStream: async () =>
          navigator.mediaDevices.getUserMedia({
            audio: {
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
              channelCount: { ideal: 1 },
            },
            video: false,
          }),
      });
      configureVoiceAudioSession("play-and-record");
      this.onAudioSession(audioSessionStatusLine());
      await this.micVad.start();
      this._enabled = true;
      this._setTurnState("listening");
      this._pingTimer = setInterval(() => this._send({ type: "ping" }), 10000);
    }

    async stop() {
      this._enabled = false;
      if (this._pingTimer) clearInterval(this._pingTimer);
      if (this._resumeTimer) clearTimeout(this._resumeTimer);
      this.tts.flush();
      if (this.micVad) {
        try {
          this.micVad.pause();
          this.micVad.destroy();
        } catch (e) {
          /* ignore */
        }
        this.micVad = null;
      }
      if (this.ws) {
        this.ws.close();
        this.ws = null;
      }
      configureVoiceAudioSession("playback");
      configureVoiceAudioSession("auto");
      this.onAudioSession(audioSessionStatusLine());
      this._setTurnState("idle");
    }

    interrupt() {
      this.tts.flush();
      this._send({ type: "interrupt" });
      this._setTurnState("listening");
    }

    _setTurnState(next) {
      this.turnState = next;
      this.onTurnState(next);
      this.onState(next);
      if (this.micVad) {
        if (next === "speaking" || next === "thinking") {
          try {
            this.micVad.pause();
          } catch (e) {
            /* ignore */
          }
        } else if (next === "listening") {
          try {
            this.micVad.start();
          } catch (e) {
            /* ignore */
          }
        }
      }
    }

    _afterSpeak() {
      if (this._resumeTimer) clearTimeout(this._resumeTimer);
      this._resumeTimer = setTimeout(() => {
        if (this._enabled && this.turnState === "speaking") {
          this._setTurnState("listening");
        }
      }, 300);
    }

    _onSpeechStart() {
      if (this.turnState !== "listening") return;
      this._send({ type: "speech.start", ts: Date.now() });
    }

    _onSpeechEnd(audio) {
      if (this.turnState !== "listening") return;
      this._sendPcmFloat32(audio);
      this._send({ type: "speech.end", ts: Date.now() });
      this._setTurnState("thinking");
    }

    _sendPcmFloat32(f32) {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const pcm = this._f32ToPcm16(f32);
      for (let off = 0; off < pcm.length; off += CHUNK_BYTES) {
        const slice = pcm.subarray(off, off + CHUNK_BYTES);
        const frame = new Uint8Array(1 + slice.length);
        frame[0] = CH_MIC;
        frame.set(slice, 1);
        this.ws.send(frame.buffer);
      }
    }

    async _connectWs() {
      const url = voiceWsUrl(this.gwV1);
      const base = String(this.gwV1 || "").replace(/\/v1\/?$/i, "");
      const khPack = await signKeyholder(base);
      this.ws = new WebSocket(url);
      this.ws.binaryType = "arraybuffer";
      await new Promise((resolve, reject) => {
        const t = setTimeout(() => reject(new Error("voice ws timeout")), 8000);
        this.ws.onopen = () => {
          clearTimeout(t);
          const hist = this.getHistory().map((m) => ({
            role: m.role,
            content: m.content || "",
          }));
          const init = {
            type: "session.init",
            session_id: this.sessionId,
            history: hist,
            lang_hint: "auto",
            tts_engine: useKokoro ? "kokoro" : "browser",
            route: "coder",
            x_route: "coder",
          };
          if (khPack && khPack.keyholder) {
            init.keyholder = khPack.keyholder;
          }
          this._send(init);
          resolve();
        };
        this.ws.onerror = () => {
          clearTimeout(t);
          reject(new Error("voice ws error"));
        };
      });
      this.ws.onmessage = (ev) => this._onMessage(ev);
      this.ws.onclose = () => {
        if (this._enabled) this.onError("voice disconnected");
      };
    }

    _send(obj) {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(obj));
      }
    }

    _onMessage(ev) {
      if (typeof ev.data === "string") {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        this._onJson(msg);
      } else if (ev.data instanceof ArrayBuffer) {
        /* CosyVoice2 server PCM — 会话线改用 speechSynthesis,忽略 */
      }
    }

    _onJson(msg) {
      const t = msg.type;
      if (t === "state") {
        /* server hint; local turnState 优先 */
      } else if (t === "llm.delta") {
        const piece = msg.text || "";
        this._subtitle += piece;
        this.onSubtitle(this._subtitle);
        if (piece.trim()) {
          if (this.turnState !== "speaking") this._setTurnState("speaking");
          this.tts.feed(piece);
        }
      } else if (t === "llm.done") {
        this.tts.flushPending();
      } else if (t === "interrupt.ack") {
        this.tts.flush();
        const spoken = msg.spoken_text || "";
        if (spoken) this.onAssistant(spoken, { interrupt: true });
        this._subtitle = spoken;
        this._setTurnState("listening");
      } else if (t === "tts.done") {
        const full = this._subtitle;
        if (full) this.onAssistant(full, { done: true });
        this._subtitle = "";
        if (this.turnState === "speaking") this._afterSpeak();
      } else if (t === "security.block") {
        this.onError("security: " + (msg.pattern_id || "blocked"));
      } else if (t === "error") {
        const detail = (msg.detail || "").trim();
        this.onError((msg.code || "error") + ": " + detail);
        if (msg.code === "initializing" || /fallback|unavailable/i.test(detail)) {
          this.onDegrade(`${msg.code}: ${detail}`);
        }
      } else if (t === "asr.final" && msg.text) {
        this._lastEmotion = msg.emotion != null ? msg.emotion : null;
        this.onAsr(msg.text, msg);
      }
    }

    _f32ToPcm16(f32) {
      const out = new Uint8Array(f32.length * 2);
      const view = new DataView(out.buffer);
      for (let i = 0; i < f32.length; i++) {
        const s = Math.max(-1, Math.min(1, f32[i]));
        view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      }
      return out;
    }
  }

  global.GridVoice = GridVoice;
  global.gridVoiceWsUrl = voiceWsUrl;
  global.gridVoiceAudioSessionStatus = audioSessionStatusLine;
})(typeof window !== "undefined" ? window : globalThis);
