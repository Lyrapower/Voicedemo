#!/usr/bin/env python3
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from scripts.garden_services import (
    music_catalog,
    resolve_music_file,
)

app = FastAPI(title="Garden Fallback Runtime", version="0.2")

HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Garden · live field</title>
  <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"/>
  <script type="importmap">
  {
    "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.165.0/build/three.module.js"
    }
  }
  </script>
  <style>
    :root{
      color-scheme:dark;
      --bg-0:#020204;
      --bg-1:#060608;
      --panel-bg:rgba(10,10,15,.93);
      --panel-border:rgba(100,181,246,.15);
      --text-primary:rgba(248,246,238,.94);
      --text-secondary:rgba(255,255,255,.70);
      --text-muted:rgba(255,255,255,.50);
      --accent-warm:#ffd700;
      --accent-bone:#f3eee1;
      --accent-green:#86d6a3;
      --accent-cyan:#64b5f6;
      --field-gold:rgba(255,215,120,.95);
      --field-cyan:rgba(70,180,230,.95);
      --danger-soft:#d85f5f;
      --ease:cubic-bezier(.4,0,.2,1);
    }
    *{box-sizing:border-box}
    html,body{
      margin:0;height:100%;overflow:hidden;color:var(--text-primary);
      background:linear-gradient(180deg,var(--bg-1),var(--bg-0));
      font-family:Inter,-apple-system,BlinkMacSystemFont,"SF Pro Display","Helvetica Neue",Arial,sans-serif;
      font-weight:400;-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision;
    }
    #scene{
      position:fixed;left:0;top:56px;right:360px;bottom:96px;display:block;z-index:2;
      width:auto;height:auto;opacity:1;
      animation:particleFade 1000ms var(--ease) forwards;
    }
    .field-watermark{
      position:fixed;left:24px;top:68px;z-index:12;pointer-events:none;
      font:600 10px/1 "SF Mono",Menlo,monospace;letter-spacing:.12em;text-transform:uppercase;
      color:rgba(100,181,246,.72);text-shadow:0 0 12px rgba(0,0,0,.8);
    }
    .field-vignette{
      position:fixed;left:0;top:56px;right:360px;bottom:96px;z-index:4;pointer-events:none;
      opacity:0;transition:opacity 420ms var(--ease), box-shadow 520ms var(--ease);
      mix-blend-mode:screen;
    }
    .field-vignette.is-listening{
      opacity:1;
      box-shadow:inset 0 0 200px 96px rgba(134,214,163,.52), inset 0 0 380px 180px rgba(20,80,50,.55);
    }
    .field-vignette.is-thinking{
      opacity:1;
      box-shadow:inset 0 0 280px 140px rgba(20,70,140,.72), inset 0 0 520px 260px rgba(0,0,0,.92);
      background:radial-gradient(ellipse 28% 38% at 52% 50%, transparent 0%, rgba(2,8,18,.78) 52%, rgba(0,0,0,.96) 100%);
      mix-blend-mode:multiply;
    }
    .field-vignette.is-speaking{
      opacity:1;
      box-shadow:inset 0 0 220px 96px rgba(255,215,120,.72), inset 0 0 420px 180px rgba(255,120,20,.42);
      background:radial-gradient(ellipse 72% 88% at 50% 42%, rgba(255,220,140,.38) 0%, transparent 58%);
    }
    .state-badge{
      position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);
      z-index:5;pointer-events:none;font:700 11px/1 "SF Mono",Menlo,monospace;
      letter-spacing:.28em;text-transform:uppercase;opacity:0;transition:opacity 380ms var(--ease);
      text-shadow:0 0 24px rgba(0,0,0,.9);
    }
    .state-badge.is-on{opacity:1;font-size:14px;transform:translate(-50%,-50%) scale(1.04)}
    .state-badge.speaking.is-on{transform:translate(-50%,-50%) scale(1.08)}
    .state-badge.thinking{color:rgba(100,200,255,.95)}
    .state-badge.speaking{color:rgba(255,215,120,.98)}
    .state-badge.listening{color:rgba(134,214,163,.95)}
    .topbar{
      position:fixed;left:0;right:0;top:0;z-index:20;height:56px;
      display:flex;align-items:center;justify-content:space-between;
      padding:0 32px;
      background:linear-gradient(180deg,rgba(2,2,4,.72),rgba(2,2,4,.16) 76%,transparent);
      font-size:11px;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);
      opacity:0;animation:uiFade 600ms var(--ease) 0ms forwards;
    }
    .topbar-left{display:flex;align-items:center;gap:18px;min-width:0}
    .topbar .brand{
      font-size:13px;width:auto;overflow:visible;letter-spacing:.18em;font-weight:600;color:var(--text-primary);
    }
    .top-status{
      display:inline-flex;align-items:center;gap:8px;font-size:10px;letter-spacing:.14em;color:var(--text-muted);
    }
    .top-status::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--accent-green)}
    .topbar .nav{display:flex;align-items:center;gap:28px;flex-shrink:0;margin-left:auto}
    .nav-music-wrap{display:inline-flex;align-items:center;gap:6px;margin-left:2px}
    .nav-music-label{
      font-size:11px;letter-spacing:.15em;text-transform:uppercase;color:var(--text-muted);opacity:.72;
    }
    .topbar .nav .nav-tab{
      position:relative;opacity:.64;transition:opacity 250ms var(--ease);
      cursor:pointer;user-select:none;border:0;background:transparent;padding:0;
      font:inherit;color:inherit;letter-spacing:inherit;text-transform:inherit;
    }
    .topbar .nav .nav-tab.is-active{opacity:1;color:var(--accent-bone)}
    .topbar .nav .nav-tab.is-active::after{
      content:"";position:absolute;left:50%;bottom:-13px;width:4px;height:4px;border-radius:50%;
      background:var(--accent-warm);transform:translateX(-50%);
    }
    .topbar .nav .nav-tab:hover{opacity:.9}
    #fieldControls{display:flex;flex-direction:column;gap:0;min-height:0}
    .control .garden-panel{
      display:none;flex:1;flex-direction:column;gap:12px;min-height:0;
      margin:0;padding:0;border:0;background:transparent;box-shadow:none;
      overflow:hidden;
    }
    .control .garden-panel.is-open{display:flex}
    .panel-head{
      display:flex;align-items:center;justify-content:space-between;gap:12px;
      font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--text-muted);
    }
    .panel-actions{display:flex;gap:8px;flex-wrap:wrap}
    .panel-btn{
      height:30px;padding:0 12px;border-radius:999px;cursor:pointer;
      border:1px solid rgba(255,255,255,.12);background:rgba(255,255,255,.06);
      color:var(--text-secondary);font:600 10px/1 "SF Mono",Menlo,monospace;
      letter-spacing:1.2px;text-transform:uppercase;
    }
    .panel-btn:hover{color:var(--accent-cyan);border-color:rgba(100,181,246,.45)}
    .panel-btn.is-on{border-color:rgba(255,215,0,.55);color:var(--accent-warm)}
    .memory-body,.music-body{flex:1;min-height:0;display:flex;flex-direction:column;gap:12px}
    .memory-preview{
      flex:1;min-height:0;overflow:auto;padding:12px 14px;border-radius:6px;
      background:rgba(0,0,0,.32);border:1px solid rgba(255,255,255,.06);
      font-size:11px;line-height:1.55;color:var(--text-primary);
      scrollbar-width:thin;
      contain:layout paint; /* 隔离面板重绘,滚动不再拖累 canvas 合成 */
    }
    .memory-preview .md-h{font-weight:700;letter-spacing:.08em;margin:4px 0 2px}
    .memory-preview .md-h1{color:var(--accent-warm);font-size:13px;text-transform:uppercase;margin-top:2px}
    .memory-preview .md-h2{color:var(--accent-cyan);font-size:11px;text-transform:uppercase;margin-top:10px}
    .memory-preview .md-h3,.memory-preview .md-h4{color:var(--accent-bone);font-size:11px}
    .memory-preview .md-ul{margin:2px 0 6px;padding-left:16px;list-style:none}
    .memory-preview .md-ul li{position:relative;margin:2px 0;color:var(--text-secondary)}
    .memory-preview .md-ul li::before{
      content:"";position:absolute;left:-12px;top:7px;width:4px;height:4px;border-radius:50%;
      background:rgba(100,181,246,.6);
    }
    .memory-preview .md-p{margin:2px 0;color:var(--text-secondary)}
    .memory-preview .md-gap{height:6px}
    .memory-preview .md-code{
      padding:1px 4px;border-radius:3px;background:rgba(100,181,246,.12);
      color:var(--accent-cyan);font-family:"SF Mono",Menlo,monospace;font-size:10px;
    }
    .memory-preview strong{color:var(--text-primary)}
    .state-idle{color:var(--text-muted)}
    .state-listening{color:var(--accent-green)}
    .state-thinking{color:var(--accent-cyan);animation:statePulse 1.6s ease-in-out infinite}
    .state-speaking{color:var(--accent-warm)}
    @keyframes statePulse{0%,100%{opacity:.55}50%{opacity:1}}
    .memory-meta{font-size:10px;color:var(--text-muted);letter-spacing:.08em}
    .session-list{display:flex;flex-direction:column;gap:6px;max-height:120px;overflow:auto}
    .session-item{
      display:flex;justify-content:space-between;gap:10px;padding:8px 10px;border-radius:6px;
      background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.06);font-size:10px;
    }
    .nav-music-select{
      width:11rem;max-width:11rem;height:28px;padding:0 24px 0 8px;border-radius:4px;cursor:pointer;
      border:1px solid rgba(100,181,246,.28);background:rgba(0,0,0,.38);
      color:var(--accent-bone);font:600 10px/1 "SF Mono",Menlo,monospace;
      letter-spacing:.14em;text-transform:uppercase;
      appearance:none;
      background-image:linear-gradient(45deg, transparent 50%, var(--accent-cyan) 50%),
        linear-gradient(135deg, var(--accent-cyan) 50%, transparent 50%);
      background-position:calc(100% - 12px) 11px, calc(100% - 8px) 11px;
      background-size:4px 4px, 4px 4px;
      background-repeat:no-repeat;
    }
    .nav-music-select:focus{outline:1px solid rgba(100,181,246,.55);outline-offset:2px}
    .nav-music-select optgroup{color:var(--text-muted);font-style:normal;font-weight:600;font-size:10px}
    .nav-music-select option{
      color:var(--text-primary);background:#0a0a0f;font-size:11px;
      text-transform:none;letter-spacing:.04em;
    }
    .nav-music-icon{
      width:26px;height:26px;padding:0;border:0;border-radius:4px;cursor:pointer;
      background:transparent;color:var(--text-muted);font-size:11px;line-height:1;
    }
    .nav-music-icon:hover{color:var(--accent-cyan)}
    .nav-music-icon.is-on{color:var(--accent-warm)}
    #musicVol{display:none}
    .save-memory.is-busy{opacity:.55;pointer-events:none}
    .top-icons{display:none}
    .icon-btn{width:16px;height:16px;display:grid;place-items:center;opacity:.62;transition:opacity 250ms var(--ease)}
    .icon-btn:hover{opacity:1}
    .control{
      position:fixed;right:24px;top:88px;bottom:96px;z-index:20;width:320px;min-width:320px;
      border-radius:8px;padding:24px;
      background:var(--panel-bg);border:1px solid var(--panel-border);
      backdrop-filter:blur(12px);
      box-shadow:0 0 20px rgba(100,181,246,.10), inset 0 0 40px rgba(10,10,15,.60);
      overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(100,181,246,.36) transparent;
      opacity:0;animation:uiFade 600ms var(--ease) 100ms forwards;
      font-family:"SF Mono","SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;
    }
    .panel-title{
      font-size:11px;letter-spacing:.16em;font-weight:600;color:var(--text-secondary);
      margin:2px 0 20px;text-transform:uppercase;
    }
    .group-title{
      margin:20px 0 12px;font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--text-muted);
    }
    .group-title:not(:first-of-type){padding-top:16px;border-top:1px solid rgba(255,255,255,.055)}
    .row{margin:0 0 17px}
    .advanced-param{display:none}
    .meta{
      display:flex;justify-content:space-between;align-items:center;
      gap:14px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-secondary);margin-bottom:8px;
      line-height:1
    }
    .meta .val{
      min-width:52px;text-align:right;color:var(--accent-cyan);font-size:13px;font-weight:600;
      font-family:"SF Mono","SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;letter-spacing:0;text-transform:none;
      opacity:1;flex-shrink:0
    }
    input[type=range]{
      --pct:50%;-webkit-appearance:none;appearance:none;width:100%;height:18px;background:transparent;cursor:pointer;
    }
    input[type=range]:focus{outline:none}
    input[type=range]:focus-visible{outline:1px solid rgba(100,181,246,.48);outline-offset:4px}
    input[type=range]::-webkit-slider-runnable-track{
      height:2px;border-radius:2px;background:linear-gradient(90deg,var(--accent-cyan) 0%,var(--accent-warm) var(--pct),rgba(255,255,255,.10) var(--pct),rgba(255,255,255,.10) 100%);
    }
    input[type=range]::-webkit-slider-thumb{
      -webkit-appearance:none;margin-top:-6px;width:14px;height:14px;border-radius:50%;
      background:var(--accent-cyan);border:0;
      box-shadow:0 0 8px rgba(100,181,246,.60);
      transition:transform .2s ease, box-shadow .2s ease;
    }
    input[type=range]::-webkit-slider-thumb:hover{
      transform:scale(1.15);box-shadow:0 0 16px rgba(100,181,246,.90);
    }
    input[type=range]::-moz-range-track{height:2px;border-radius:2px;background:rgba(255,255,255,.10)}
    input[type=range]::-moz-range-progress{height:2px;border-radius:2px;background:var(--accent-cyan)}
    input[type=range]::-moz-range-thumb{
      width:14px;height:14px;border-radius:50%;background:var(--accent-cyan);border:0;
      box-shadow:0 0 8px rgba(100,181,246,.60)
    }
    .save-memory{
      position:relative;left:auto;right:auto;bottom:auto;z-index:1;height:36px;border-radius:999px;
      border:1px solid rgba(255,255,255,.10);background:rgba(255,255,255,.06);padding:0 14px;
      color:var(--text-secondary);font:600 10px/1 "SF Mono",Menlo,monospace;
      letter-spacing:1.5px;text-transform:uppercase;cursor:pointer;
      transition:color 250ms var(--ease),opacity 250ms var(--ease),border-color .3s ease,box-shadow .3s ease;
      opacity:1;animation:none;
    }
    .save-memory:hover{color:var(--accent-cyan)}
    .bottom-dock{
      position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:24;height:64px;
      display:flex;align-items:center;gap:16px;padding:10px 18px;border-radius:999px;
      background:rgba(8,8,10,.58);border:1px solid rgba(255,255,255,.10);
      backdrop-filter:blur(14px);opacity:0;animation:uiFade 600ms var(--ease) 180ms forwards;
    }
    .mic{
      position:relative;left:auto;bottom:auto;transform:none;z-index:1;
      width:40px;height:40px;border-radius:50%;border:1px solid rgba(255,255,255,.14);
      background:rgba(255,255,255,.08);display:grid;place-items:center;
      color:var(--text-secondary);font-size:0;letter-spacing:0;cursor:pointer;
      transition:border-color 250ms var(--ease),opacity 250ms var(--ease);
      opacity:1;animation:none;
    }
    .mic::before{
      content:"";width:10px;height:15px;border:1px solid currentColor;border-radius:7px 7px 5px 5px;
    }
    .mic::after{
      content:"";position:absolute;width:18px;height:18px;border-bottom:1px solid currentColor;border-radius:0 0 12px 12px;top:17px;left:10px;
    }
    .mic:hover{border-color:rgba(245,240,232,.34)}
    .mic.is-recording{border-color:rgba(91,159,191,.72);box-shadow:0 0 12px rgba(100,181,246,.45)}
    .analysis{
      position:fixed;left:40px;bottom:40px;z-index:22;width:280px;padding:16px 20px;
      border-radius:6px;background:rgba(10,10,15,.75);border:1px solid rgba(100,181,246,.20);
      backdrop-filter:blur(8px);box-shadow:0 12px 40px rgba(0,0,0,.35);
      font-family:"SF Mono","SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;
      font-size:12px;line-height:1.45;color:var(--text-secondary);
      opacity:0.85;transition:opacity .3s ease;
      animation:uiFade 600ms var(--ease) 140ms forwards;
    }
    .analysis:hover,.analysis.is-live{opacity:1}
    .analysis-title{
      font-size:10px;letter-spacing:1.2px;text-transform:uppercase;color:var(--text-muted);margin-bottom:10px;
    }
    .analysis-row{display:flex;justify-content:space-between;gap:12px;margin:6px 0}
    .analysis-row .k{color:var(--text-muted)}
    .analysis-row .v{color:var(--accent-cyan);text-align:right;font-weight:600}
    .analysis-row .v.live{color:var(--accent-green)}
    .analysis-row .v.stub{color:var(--accent-warm)}
    .coherence-bar{
      width:100%;height:3px;background:rgba(255,255,255,.10);border-radius:2px;margin-top:8px;overflow:hidden;
    }
    .coherence-fill{
      height:100%;width:0%;
      background:linear-gradient(90deg,var(--accent-cyan),var(--accent-warm));
      transition:width .2s ease;
      box-shadow:0 0 8px rgba(100,181,246,.60);
    }
    #specCanvas{
      display:block;width:100%;height:72px;margin:10px 0 8px;border-radius:10px;
      background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.06);
    }
    .band-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:8px}
    .band{
      height:4px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden;
    }
    .band i{
      display:block;height:100%;width:0%;border-radius:999px;transition:width 80ms linear;
    }
    .band.low i{background:var(--accent-green)}
    .band.mid i{background:var(--accent-cyan)}
    .band.high i{background:var(--accent-warm)}
    .hud{
      position:fixed;left:24px;top:60px;z-index:22;
      padding:10px 14px;border-radius:6px;
      background:rgba(10,10,15,.58);border:1px solid rgba(255,215,120,.14);
      backdrop-filter:blur(8px);
      font-family:"SF Mono","SFMono-Regular",ui-monospace,Menlo,Consolas,monospace;
      font-size:10px;line-height:1.4;letter-spacing:.04em;color:var(--text-secondary);
      white-space:pre-line;font-variant-numeric:tabular-nums;
      opacity:0;animation:uiFade 600ms var(--ease) 120ms forwards;
      pointer-events:none;max-width:min(320px,42vw);
    }
    .presence-btn{
      position:relative;left:auto;bottom:auto;z-index:1;
      padding:0 22px;height:40px;border-radius:24px;cursor:pointer;
      border:2px solid rgba(100,181,246,.40);background:rgba(10,10,15,.90);
      color:var(--accent-cyan);font:600 12px/1 "SF Mono",Menlo,monospace;letter-spacing:2px;
      box-shadow:0 0 20px rgba(100,181,246,.30), inset 0 0 20px rgba(10,10,15,.80);
    }
    .presence-btn:hover{
      border-color:rgba(100,181,246,.80);
      box-shadow:0 0 30px rgba(100,181,246,.50), inset 0 0 30px rgba(10,10,15,.60);
      transform:scale(1.04);
    }
    .presence-btn.is-on{
      background:rgba(100,181,246,.15);border-color:var(--accent-warm);color:var(--accent-warm);
      box-shadow:0 0 40px rgba(255,215,0,.40), inset 0 0 40px rgba(255,215,0,.10);
    }
    @keyframes uiFade{from{opacity:0}to{opacity:1}}
    @keyframes particleFade{from{opacity:0}to{opacity:1}}
    @keyframes micPulse{0%,100%{border-color:rgba(255,255,255,.2)}50%{border-color:rgba(91,159,191,.72)}}
    @media (max-width:1024px){
      #scene{right:28px;bottom:96px}
      .field-vignette{right:28px}
      .control{right:0;top:72px;bottom:0;width:288px;min-width:288px;transform:translateX(calc(100% - 28px));transition:transform 250ms var(--ease)}
      .control:hover,.control:focus-within{transform:translateX(0)}
      .bottom-dock{height:56px}
    }
    @media (max-width:767px){
      .control{display:none}
      .chip{left:18px;top:84px}
      .topbar .nav{gap:12px;font-size:11px;letter-spacing:1.2px}
      .nav-music-select{width:8.5rem;max-width:8.5rem}
    }
  </style>
</head>
<body>
  <canvas id="scene"></canvas>
  <div class="field-vignette" aria-hidden="true"></div>
  <div id="stateBadge" class="state-badge" aria-hidden="true"></div>
  <div class="topbar">
    <div class="topbar-left">
      <div class="brand">VOICE GARDEN</div>
      <div class="top-status">IMMERSIVE FIELD · LIVE</div>
    </div>
    <div class="nav" role="tablist" aria-label="Garden views">
      <button type="button" class="nav-tab is-active" data-view="garden" role="tab" aria-selected="true">GARDEN</button>
      <button type="button" class="nav-tab" data-view="memory" role="tab" aria-selected="false">MEMORY</button>
      <span class="nav-music-wrap" aria-label="Music">
        <span class="nav-music-label">MUSIC</span>
        <select id="musicSelect" class="nav-music-select" title="Choose song or background"></select>
        <button type="button" id="musicPlayBtn" class="nav-music-icon" title="Play / pause" aria-label="Play">▶</button>
        <button type="button" id="musicUploadBtn" class="nav-music-icon" title="Upload" aria-label="Upload">↑</button>
        <input id="musicUpload" type="file" accept="audio/*" hidden/>
        <input id="musicVol" type="range" min="0" max="100" step="1" value="42" hidden/>
      </span>
    </div>
  </div>
  <aside class="control">
    <div id="fieldControls">
    <div class="panel-title">FIELD CONTROLS</div>
    <div class="group-title">Field</div>
    <div class="row"><div class="meta"><span>Dispersion</span><span id="vDisp" class="val">1.4</span></div><input id="disp" type="range" min="0.7" max="2.8" step="0.1" value="1.4"/></div>
    <div class="row"><div class="meta"><span>Particle Size</span><span id="vSize" class="val">1.0</span></div><input id="size" type="range" min="0.4" max="2.0" step="0.05" value="1.0"/></div>
    <div class="row"><div class="meta"><span>Contrast</span><span id="vContrast" class="val">1.3</span></div><input id="contrast" type="range" min="0.7" max="2.2" step="0.1" value="1.3"/></div>
    <div class="group-title">Depth</div>
    <div class="row"><div class="meta"><span>Depth Strength</span><span id="vDepth" class="val">1.0</span></div><input id="depth" type="range" min="0.3" max="2.2" step="0.1" value="1.0"/></div>
    <div class="row"><div class="meta"><span>Mouse Radius</span><span id="vMouse" class="val">120</span></div><input id="mouse" type="range" min="40" max="220" step="5" value="120"/></div>
    <div class="group-title">Motion</div>
    <div class="row"><div class="meta"><span>Flow Speed</span><span id="vFlow" class="val">1.0</span></div><input id="flow" type="range" min="0.2" max="2.0" step="0.1" value="1.0"/></div>
    <div class="row"><div class="meta"><span>Flow Amplitude</span><span id="vFlowAmp" class="val">1.0</span></div><input id="flowAmp" type="range" min="0.3" max="2.5" step="0.1" value="1.0"/></div>
    <div class="group-title">Audio</div>
    <div class="row"><div class="meta"><span>Dance Strength</span><span id="vDance" class="val">0.9</span></div><input id="dance" type="range" min="0.1" max="2.0" step="0.1" value="0.9"/></div>
    <div class="row"><div class="meta"><span>Depth Wave</span><span id="vDepthWave" class="val">0.8</span></div><input id="depthWave" type="range" min="0.1" max="2.0" step="0.1" value="0.8"/></div>
    <div class="row advanced-param"><div class="meta"><span>Color Shift Speed</span><span id="vColorShift" class="val">0.8</span></div><input id="colorShift" type="range" min="0.1" max="2.0" step="0.1" value="0.8"/></div>
    </div>
    <section id="memoryPanel" class="garden-panel view-memory" aria-label="Compiled memory" hidden>
      <div class="panel-head">
        <span>Compiled memory</span>
        <div class="panel-actions">
          <button type="button" id="memoryRefresh" class="panel-btn">Refresh</button>
          <button type="button" id="memoryCompile" class="panel-btn">Compile</button>
        </div>
      </div>
      <div class="memory-body">
        <div id="memoryMeta" class="memory-meta">loading…</div>
        <pre id="memoryPreview" class="memory-preview">—</pre>
        <div class="panel-head"><span>Local snapshots</span></div>
        <div id="sessionList" class="session-list"></div>
      </div>
    </section>
  </aside>
  <div id="analysis" class="analysis">
    <div class="analysis-title">Live Analyzer</div>
    <canvas id="specCanvas" width="248" height="72" aria-label="frequency spectrum"></canvas>
    <div class="analysis-row"><span class="k">mic</span><span id="aMic" class="v">idle</span></div>
    <div class="analysis-row"><span class="k">presence</span><span id="aPresence" class="v stub">off</span></div>
    <div class="analysis-row"><span class="k">voice Hz</span><span id="aVoice" class="v">—</span></div>
    <div class="analysis-row"><span class="k">ai Hz</span><span id="aAi" class="v">—</span></div>
    <div class="analysis-row"><span class="k">coherence</span><span id="aCoh" class="v">—</span></div>
    <div class="analysis-row"><span class="k">beat</span><span id="aBeat" class="v">—</span></div>
    <div class="analysis-row"><span class="k">state</span><span id="aState" class="v">—</span></div>
    <div class="analysis-row"><span class="k">energy</span><span id="aEnergy" class="v">—</span></div>
    <div class="coherence-bar" aria-hidden="true"><div id="cohFill" class="coherence-fill"></div></div>
    <div class="band-row">
      <div class="band low"><i id="bLow"></i></div>
      <div class="band mid"><i id="bMid"></i></div>
      <div class="band high"><i id="bHigh"></i></div>
    </div>
  </div>
  <div id="hud" class="hud">starting...</div>
  <div class="bottom-dock">
    <button id="micBtn" class="mic" type="button" aria-label="Microphone off"></button>
    <button id="speakBtn" class="presence-btn" type="button">Presence</button>
    <button id="echoTestBtn" class="presence-btn" type="button" title="Trigger TTS · thinking → speaking">Echo</button>
    <button id="saveMemory" class="save-memory" type="button">Save Memory</button>
  </div>
  <script type="module">
    import * as THREE from "three";
    console.info("[Garden] blue-gold v2.1 · phase-accum + wired field morph");
    const canvas = document.getElementById("scene");
    const hud = document.getElementById("hud");
    const analysis = document.getElementById("analysis");
    const controls = {
      disp:1.4,size:0.95,contrast:1.35,flow:1.0,flowAmp:1.0,depth:1.0,mouse:120,colorShift:0.8,dance:0.75,depthWave:0.65
    };
    const timerT0 = performance.now();
    let lastControl = "init";
    let lastControlAt = 0;
    const updateRangeFill=(el)=>{
      const min=parseFloat(el.min || "0");
      const max=parseFloat(el.max || "100");
      const val=parseFloat(el.value || "0");
      const pct=((val-min)/Math.max(0.0001,max-min))*100;
      el.style.setProperty("--pct", pct.toFixed(2) + "%");
    };
    const bind=(id,key,out,digits=1)=>{
      const el=document.getElementById(id);
      const v=document.getElementById(out);
      if(!el || !v){ return; }
      updateRangeFill(el);
      el.addEventListener("input",(e)=>{
        controls[key]=parseFloat(e.target.value);
        v.textContent=controls[key].toFixed(digits);
        updateRangeFill(el);
        lastControl = key + "=" + controls[key].toFixed(digits);
        lastControlAt = performance.now();
      });
    };
    bind("disp","disp","vDisp"); bind("size","size","vSize"); bind("contrast","contrast","vContrast");
    bind("flow","flow","vFlow"); bind("flowAmp","flowAmp","vFlowAmp"); bind("depth","depth","vDepth");
    bind("mouse","mouse","vMouse",0); bind("colorShift","colorShift","vColorShift"); bind("dance","dance","vDance"); bind("depthWave","depthWave","vDepthWave");
    const syncControlLabels=()=>{
      const pairs=[
        ["disp","vDisp",1],["size","vSize",1],["contrast","vContrast",1],["flow","vFlow",1],["flowAmp","vFlowAmp",1],
        ["depth","vDepth",1],["mouse","vMouse",0],["colorShift","vColorShift",1],["dance","vDance",1],["depthWave","vDepthWave",1]
      ];
      for(const [key,out,digits] of pairs){
        const el=document.getElementById(key);
        const v=document.getElementById(out);
        if(el && v){ v.textContent=controls[key].toFixed(digits); updateRangeFill(el); }
      }
    };
    syncControlLabels();

    let mouseX=0, mouseY=0;
    const FIGURE_X = -38.0;
    const VIEW_AIM_X = FIGURE_X + 34.0;
    const renderer = new THREE.WebGLRenderer({canvas, antialias:false, alpha:false, powerPreference:"high-performance"});
    renderer.setPixelRatio(Math.min(2,window.devicePixelRatio));
    renderer.setClearColor(0x030408,1);
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.toneMappingExposure = 2.92;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(53,window.innerWidth/window.innerHeight,0.1,520);
    camera.position.set(VIEW_AIM_X, 0, 98);
    const setRenderSize = () => {
      const rect = canvas.getBoundingClientRect();
      const w = Math.max(1, Math.floor(rect.width));
      const h = Math.max(1, Math.floor(rect.height));
      renderer.setSize(w,h,false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    setRenderSize();
    canvas.style.opacity = "1";
    window.addEventListener("pointermove",(e)=>{mouseX=(e.clientX/window.innerWidth-0.5)*2;mouseY=(e.clientY/window.innerHeight-0.5)*2;});

    function profile(t){
      const shoulder = 19.5*(1-Math.min(1,Math.abs(t+0.54)*1.22));
      const torso = 13.8*(1-Math.abs(t)*0.56);
      const crown = 9.2*Math.exp(-((t-0.13)*(t-0.13))*8.2);
      const face = 4.1*Math.exp(-((t-0.24)*(t-0.24))*58);
      const throat = -2.4*Math.exp(-((t+0.42)*(t+0.42))*38);
      const waist = 2.8*Math.exp(-((t+0.08)*(t+0.08))*22);
      return Math.max(3.4, torso + shoulder + crown + face + throat + waist);
    }

    function makeLayer(count, spread, zSpread, mode="field"){
      const pos = new Float32Array(count*3);
      const base = new Float32Array(count*3);
      const phase = new Float32Array(count);
      let xBias = 0;
      if(mode === "edge"){ xBias = -spread * 2.6; }
      else if(mode === "edgeCyan"){ xBias = spread * 1.6; }
      else if(mode === "edgeCoral"){ xBias = -spread * 1.2; }
      const surfacePow = mode === "dust" ? 0.86 : 0.48;
      for(let i=0;i<count;i++){
        const t = Math.random()*2-1;
        const y = t*56;
        const shell = profile(t);
        const surface = Math.pow(Math.random(), surfacePow);
        const angle = (Math.random() * Math.PI * 2.0) + Math.sin(t*3.2)*0.35;
        const squash = mode === "core" ? 0.34 : mode === "halo" ? 0.48 : 0.62;
        const bodyBias = mode === "edge" || mode === "edgeCyan" || mode === "edgeCoral" ? 0.78 : 0.55;
        const edgePull = mode === "edge" || mode === "edgeCyan" || mode === "edgeCoral" ? 0.72 : 0.38;
        const x = (Math.cos(angle)*shell*spread*squash*surface) + shell*spread*bodyBias*edgePull + (Math.random()-0.5)*(4.2*spread) + xBias;
        const z = Math.sin(angle)*zSpread*surface + (Math.random()-0.5)*zSpread*0.18 + Math.sin(i*0.001)*4;
        const idx=i*3;
        pos[idx]=x; pos[idx+1]=y+(Math.random()-0.5)*1.6; pos[idx+2]=z;
        base[idx]=pos[idx]; base[idx+1]=pos[idx+1]; base[idx+2]=pos[idx+2];
        phase[i]=Math.random()*6.283;
      }
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(pos,3));
      return {count, geo, base, phase};
    }

    const core = makeLayer(42000,0.92,22,"core");
    const halo = makeLayer(32000,1.12,32,"halo");
    const fringeGreen = makeLayer(15000,1.22,38,"edge");
    const fringeCyan = makeLayer(15000,1.28,42,"edgeCyan");
    const fringeCoral = makeLayer(9000,1.12,36,"edgeCoral");
    const dust = makeLayer(52000,1.42,118,"dust");

    function material(kind, fieldBias=0.0, blendingMode = THREE.AdditiveBlending){
      return new THREE.ShaderMaterial({
        uniforms:{
          uSize:{value:1.18}, uAmp:{value:0.2}, uShift:{value:0.0}, uKind:{value:kind}, uFieldBias:{value:fieldBias}, uTime:{value:0.0}
        },
        vertexShader:`
          uniform float uSize; uniform float uAmp; uniform float uKind; uniform float uFieldBias; uniform float uTime;
          varying float vDepth;
          varying float vSide;
          varying float vSpark;
          varying float vBeat;
          void main(){
            vec4 mv = modelViewMatrix * vec4(position,1.0);
            vSide = smoothstep(-2.0, 11.0, position.x + uFieldBias * 5.0);
            vSpark = fract(sin(dot(position.xy, vec2(127.1, 311.7))) * 43758.5453);
            vBeat = fract(sin(dot(position.yz, vec2(41.7, 89.1))) * 23421.631);
            float h = fract(sin(dot(position.xy, vec2(127.1, 311.7))) * 43758.5453);
            float sizeJitter = mix(0.62, 1.48, h);
            if(uKind < 1.5){ sizeJitter *= mix(0.88, 1.18, h); }
            else if(uKind < 2.5){ sizeJitter *= mix(1.0, 1.55, h); }
            else if(uKind > 4.5){ sizeJitter *= mix(0.48, 0.88, h); }
            float depthScale = clamp((220.0 + mv.z) / 220.0, 0.32, 1.85);
            float k = 0.48;
            if(uKind < 0.5){ k = 0.68; }
            else if(uKind < 1.5){ k = 0.88; }
            else if(uKind < 4.5){ k = 0.82; }
            else { k = 0.34; }
            float pulseSize = 1.0 + sin(uTime * 3.2 + vSpark * 6.283) * 0.08 * (0.5 + uAmp);
            gl_PointSize = uSize * k * sizeJitter * pulseSize * (196.0 / max(20.0, -mv.z)) * depthScale * (1.0 + uAmp*0.45);
            vDepth = clamp((-mv.z)/220.0,0.0,1.0);
            gl_Position = projectionMatrix * mv;
          }
        `,
        fragmentShader:`
          uniform float uAmp; uniform float uShift; uniform float uKind; uniform float uTime;
          varying float vDepth;
          varying float vSide;
          varying float vSpark;
          varying float vBeat;
          vec3 fireSpectrum(float u){
            u = fract(u);
            float x = u * 4.0;
            if(x < 1.0){ return mix(vec3(1.00,1.00,1.00), vec3(0.28,0.62,1.00), x); }
            if(x < 2.0){ return mix(vec3(0.28,0.62,1.00), vec3(0.92,0.48,0.06), x - 1.0); }
            if(x < 3.0){ return mix(vec3(0.92,0.48,0.06), vec3(0.20,0.82,0.48), x - 2.0); }
            return mix(vec3(0.20,0.82,0.48), vec3(0.95,0.22,0.12), x - 3.0);
          }
          float livingShard(float ang, float r, float facetShift, float energy){
            float brick = abs(fract((ang + facetShift) * 5.72958) - 0.5) * 2.0;
            float edge = pow(max(0.0, 1.0 - brick), 8.0);
            float g5 = pow(max(0.0, cos(ang * 5.0 + facetShift)), 14.0 + energy * 6.0);
            float g10 = pow(max(0.0, cos(ang * 10.0 + facetShift * 1.3)), 22.0 + energy * 8.0);
            float g16 = pow(max(0.0, cos(ang * 16.0 + facetShift * 0.7)), 32.0 + energy * 10.0);
            return max(g5, max(g10, g16)) * (1.0 + edge * 2.5) * exp(-r * 4.8) * energy;
          }
          void main(){
            vec2 uv = gl_PointCoord - 0.5;
            float r = length(uv);
            float ang = atan(uv.y, uv.x);
            float halo = smoothstep(0.74, 0.14, r);
            float bokehBig = exp(-r * r * 2.0);
            float bokehMid = exp(-r * r * 8.0);
            float pin = exp(-r * r * 36.0);
            float goldRing = exp(-pow((r - 0.24) * 5.5, 2.0));
            float blueRing = exp(-pow((r - 0.20) * 5.5, 2.0));
            float depthFade = mix(1.22, 0.74, vDepth);
            float side = clamp(vSide, 0.0, 1.0);
            float goldSide = 1.0 - side;
            float life = 0.52 + 0.48 * sin(uTime * 2.6 + vSpark * 6.283);
            float flicker = 0.42 + 0.58 * sin(uTime * 7.4 + vBeat * 12.566);
            float breath = 0.58 + 0.42 * sin(uTime * 1.05 + vSpark * 3.14);
            float energy = life * flicker * breath * (0.62 + uAmp * 0.88);
            float facetShift = uShift * 0.18 + uTime * 0.42 + vBeat * 0.35;
            if(uKind > 1.5 && uKind < 2.5){ facetShift += 0.52; }
            else if(uKind > 2.5 && uKind < 3.5){ facetShift += 0.08; }
            else if(uKind > 3.5 && uKind < 4.5){ facetShift += 0.74; }
            float angLive = ang + uTime * 1.35 + vSpark * 2.1;
            float shard = livingShard(angLive, r, facetShift, energy);
            float facetU = fract(angLive * 1.2732395 + facetShift + r * 0.55);
            float band = floor(facetU * 5.0) / 5.0;
            vec3 fire = mix(fireSpectrum(band + 0.04), fireSpectrum(band + 0.22), smoothstep(0.1, 0.9, fract(facetU * 5.0)));
            float veil = halo * 0.14 + bokehBig * 0.08;
            float peak = pin * energy + shard * 1.55 + goldRing * energy * 0.68;
            vec3 metalGold = vec3(0.98, 0.48, 0.02);
            vec3 gleamGold = vec3(1.00, 0.66, 0.04);
            vec3 flashGold = vec3(1.00, 0.92, 0.55);
            vec3 goldCol = metalGold * veil * life * 0.32;
            goldCol += gleamGold * (bokehMid * energy * 0.42 + goldRing * energy * 0.28);
            goldCol += flashGold * peak * 1.12;
            goldCol += gleamGold * fire * shard * 0.45;
            float goldA = (veil * 0.12 + peak * 0.68) * (0.40 + uAmp * 0.48) * depthFade;
            float peakB = pin * energy + shard * 1.28 + blueRing * energy * 0.62;
            vec3 blueCol = vec3(0.04, 0.34, 1.05) * (veil + bokehMid * 0.32) * energy;
            blueCol += vec3(0.28, 0.78, 1.55) * peakB * 1.08;
            blueCol += vec3(0.18, 0.58, 1.22) * fire * shard * 0.32 * side;
            float blueA = (veil * 0.12 + peakB * 0.62) * (0.38 + uAmp * 0.46) * depthFade;
            vec3 col = mix(goldCol, blueCol, side) * 1.08;
            float a = mix(goldA, blueA, side);
            if(uKind > 2.5 && uKind < 3.5){
              col = mix(col, vec3(0.08, 0.78, 1.68), 0.68 * side);
              a *= mix(1.05, 1.42, side);
            }else if(uKind > 4.5){
              a *= mix(0.68, 0.30, side);
            }
            if(a < 0.004) discard;
            gl_FragColor = vec4(col, a);
          }
        `,
        transparent:true, depthWrite:false, blending:blendingMode
      });
    }

    const mCore = material(0, 0.0);
    const mHalo = material(1, 0.0);
    const mGreen = material(2, -0.35);
    const mCyan = material(3, 0.72);
    const mCoral = material(4, -0.25);
    const mDust = material(5, 0.0);
    const particleMats = [mCore, mHalo, mGreen, mCyan, mCoral, mDust];
    const pCore = new THREE.Points(core.geo,mCore);
    const pHalo = new THREE.Points(halo.geo,mHalo);
    const pGreen = new THREE.Points(fringeGreen.geo,mGreen);
    const pCyan = new THREE.Points(fringeCyan.geo,mCyan);
    const pCoral = new THREE.Points(fringeCoral.geo,mCoral);
    const pDust = new THREE.Points(dust.geo,mDust);
    scene.add(pDust); scene.add(pCoral); scene.add(pCyan); scene.add(pGreen); scene.add(pHalo); scene.add(pCore);

    window.addEventListener("resize",()=>{ setRenderSize(); });

    const key = new THREE.PointLight(0xfff0d8,3.8,520); key.position.set(-8,22,28); scene.add(key);
    const rimGreen = new THREE.PointLight(0x86d6a3,0.65,340); rimGreen.position.set(-18,-12,36); scene.add(rimGreen);
    const rimCyan = new THREE.PointLight(0x70d8ff,2.35,360); rimCyan.position.set(18,10,32); scene.add(rimCyan);
    const rimGold = new THREE.PointLight(0xff9020,1.35,340); rimGold.position.set(-28,8,28); scene.add(rimGold);
    const rimCoral = new THREE.PointLight(0xd8c38a,0.45,290); rimCoral.position.set(-20,9,24); scene.add(rimCoral);

    const PARTICLE_COUNT = 42000 + 32000 + 15000 + 15000 + 9000 + 52000;
    const MAX_FREQ_HZ = 8000;
    const API_BASE = (location.port === "5173") ? "http://127.0.0.1:8787" : location.origin;
    const TELEMETRY_URL = `${API_BASE}/api/telemetry`;
    const VOICE_URL = `${API_BASE}/api/voice`;
    const SPEAK_URL = `${API_BASE}/api/speak`;
    const PRESENCE_URL = `${API_BASE}/api/presence`;
    const GARDEN_API = (location.port === "5173") ? "http://127.0.0.1:8787" : location.origin;
    const HEALTH_URL = `${GARDEN_API}/health`;
    const MEMORY_COMPILED_URL = `${GARDEN_API}/api/memory/compiled`;
    const MEMORY_COMPILE_URL = `${GARDEN_API}/api/memory/compile`;
    const MUSIC_CATALOG_URL = `${GARDEN_API}/api/music/catalog`;
    const SESSIONS_KEY = "voice-garden-snapshots-v1";
    const MUSIC_PREF_KEY = "voice-garden-music-track-v1";
    let channelOnline = false;
    let substrateHudLines = ["8787 /health pending"];
    async function pullSubstrateHealth(){
      try{
        const r = await fetch(HEALTH_URL);
        if(!r.ok){ throw new Error(String(r.status)); }
        const data = await r.json();
        const lines = data?.substrate?.hud_lines;
        if(Array.isArray(lines) && lines.length){
          substrateHudLines = lines.map((x)=>String(x));
        }else{
          substrateHudLines = ["substrate block missing from /health"];
        }
        channelOnline = true;
      }catch(err){
        channelOnline = false;
        substrateHudLines = ["8787 /health unreachable"];
        console.warn("[substrate health]", err);
      }
    }
    pullSubstrateHealth();
    setInterval(pullSubstrateHealth, 5000);
    let presenceTouchedAt = 0;
    let presenceSyncedOnce = false;

    // 八度等价的 coherence:log2 域测音程距离,折叠到最近八度。
    // 高八度哼同一个音也算和谐;半音(1/12 oct)外迅速衰减。
    // sigma=0.04 oct ≈ 半个半音的容差 —— 对齐需要真的"调准"。
    function coherenceOctave(voiceHz, aiHz){
      const v = Math.max(1, voiceHz);
      const a = Math.max(1, aiHz);
      const ratio = Math.log2(v / a);
      const d = ratio - Math.round(ratio); // 折叠八度
      const sigma = 0.04;
      return Math.exp(-(d * d) / (2 * sigma * sigma));
    }
    function coherenceSimple(voiceHz, aiHz){
      return coherenceOctave(voiceHz, aiHz);
    }
    function computeParticleDrive(tel, voiceHzMic, micActive, analyserAmp, analyserFreq){
      const hasMic = micActive && voiceHzMic > 30;
      const hasTelVoice = tel.voiceSource === "mic" && (tel.voiceFreq || 0) > 30;
      const voiceHz = hasMic ? voiceHzMic : (hasTelVoice ? tel.voiceFreq : 0);
      const aiActive = !!(tel.speaking || tel.aiSource === "macos_say" || tel.aiSource === "kokoro" || tel.aiSource === "presence_echo");
      const aiHz = aiActive ? (tel.aiFreq || 0) : 0;
      const aiAmplitude = aiActive ? (tel.aiAmplitude || 0) : 0;
      const coherence = (voiceHz > 0 && aiHz > 0) ? coherenceSimple(voiceHz, aiHz) : 0;
      const energy = Math.min(1, coherence * 0.55 + aiAmplitude * 0.35 + analyserAmp * 0.45);
      const amp = Math.min(1, Math.max(0.08, energy * 0.85 + analyserAmp * 0.55));
      const freq = Math.max(120, (analyserFreq > 10 ? analyserFreq : voiceHz) * 0.65 + aiHz * 0.35);
      return {coherence, energy, amp, freq, voiceHz, aiHz, aiAmplitude, hasMic, aiActive};
    }

    let telemetry={mode:"stub",voiceSource:"synthetic",voiceFreq:220,aiFreq:220,aiAmplitude:0.12,latencyMs:24};
    let telemetryLive = false;
    let latencyAvg = 24;
    let micReady = false;
    let micAmp = 0;
    let micFreq = 0;            // 0 = 无人声;不再预设假的 220
    let micFreqAt = 0;
    const VOICE_BAND_LOW = 80;    // Hz,人声基频下限
    const VOICE_BAND_HIGH = 600;  // Hz,覆盖高音女声/儿童
    const VOICE_PEAK_GATE = 70;   // 0-255 字节谱峰值门限
    const VOICE_AMP_GATE = 0.015; // 整体能量门限
    const VOICE_HOLD_MS = 900;    // 静音后保持读数的毫秒数
    let micLow = 0;
    let micMid = 0;
    let micHigh = 0;
    let micCtx = null;
    let micAnalyser = null;
    let micData = null;
    const specPeaks = new Float32Array(48); // 频谱 peak-hold 状态
    let lastBeatHz = 0;
    // aiState 四态权重(平滑过渡,避免状态切换时画面跳变)
    const stateW = { idle: 1, listening: 0, thinking: 0, speaking: 0 };
    let swirlPhase = 0; // thinking 盘旋的累积相位
    let lastStateTs = 0;
    let thinkingLatchT = 0;
    let displayedState = "idle";
    const THINKING_MIN_MS = 2000;
    const fieldVignette = document.querySelector(".field-vignette");
    const stateBadge = document.getElementById("stateBadge");
    let presenceOn = false;
    let lastVoicePost = 0;
    const micBtn = document.getElementById("micBtn");
    const speakBtn = document.getElementById("speakBtn");
    const echoTestBtn = document.getElementById("echoTestBtn");
    const specCanvas = document.getElementById("specCanvas");
    const specCtx = specCanvas ? specCanvas.getContext("2d") : null;
    const aMic = document.getElementById("aMic");
    const aPresence = document.getElementById("aPresence");
    const aVoice = document.getElementById("aVoice");
    const aAi = document.getElementById("aAi");
    const aCoh = document.getElementById("aCoh");
    const aBeat = document.getElementById("aBeat");
    const aState = document.getElementById("aState");
    const aEnergy = document.getElementById("aEnergy");
    const bLow = document.getElementById("bLow");
    const bMid = document.getElementById("bMid");
    const bHigh = document.getElementById("bHigh");
    const cohFill = document.getElementById("cohFill");

    if(!micBtn || !speakBtn){
      console.error("[Garden] missing mic or presence button in DOM");
    }
    async function startMic(){
      if(micReady){ return; }
      try{
        const stream = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
        micCtx = new (window.AudioContext || window.webkitAudioContext)();
        if(micCtx.state === "suspended"){ await micCtx.resume(); }
        const src = micCtx.createMediaStreamSource(stream);
        micAnalyser = micCtx.createAnalyser();
        micAnalyser.fftSize = 2048;
        micAnalyser.smoothingTimeConstant = 0.72;
        micData = new Uint8Array(micAnalyser.frequencyBinCount);
        src.connect(micAnalyser);
        micReady = true;
        micBtn.classList.add("is-recording");
        micBtn.setAttribute("aria-label", "Microphone on");
        aMic.textContent = "listening";
        aMic.className = "v live";
        analysis.classList.add("is-live");
      }catch(err){
        micReady = false;
        micBtn.classList.remove("is-recording");
        micBtn.setAttribute("aria-label", "Microphone denied");
        aMic.textContent = "denied";
        aMic.className = "v stub";
        console.warn("[Garden mic]", err);
      }
    }
    micBtn?.addEventListener("click", startMic);
    function applyPresenceUi(){
      if(!speakBtn){ return; }
      speakBtn.textContent = presenceOn ? "Presence ON" : "Presence";
      speakBtn.classList.toggle("is-on", presenceOn);
      if(aPresence){
        aPresence.textContent = presenceOn ? "on" : "off";
        aPresence.className = "v " + (presenceOn ? "live" : "stub");
      }
    }
    speakBtn?.addEventListener("click", async ()=>{
      presenceOn = !presenceOn;
      presenceTouchedAt = performance.now();
      applyPresenceUi();
      try{
        const r = await fetch(PRESENCE_URL, {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({enabled: presenceOn})
        });
        if(!r.ok){ throw new Error("presence " + r.status); }
        channelOnline = true;
      }catch(err){
        channelOnline = false;
        presenceOn = !presenceOn;
        applyPresenceUi();
        if(aPresence){
          aPresence.textContent = "error";
          aPresence.className = "v stub";
        }
      }
    });
    let morphDemoOn = false;
    let morphDemoT = 0;
    echoTestBtn?.addEventListener("click", async (e)=>{
      if(e.shiftKey){
        morphDemoOn = true;
        morphDemoT = performance.now();
        console.info("[Garden] morph demo: idle→listening→thinking→speaking (2.2s each)");
        return;
      }
      morphDemoOn = false;
      try{
        const r = await fetch(SPEAK_URL, {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({text: "I'm here."})
        });
        if(!r.ok){ throw new Error("speak " + r.status); }
        channelOnline = true;
      }catch(err){
        channelOnline = false;
        console.warn("[Garden echo]", err);
      }
    });

    async function pullTelemetry(){
      const t0 = performance.now();
      try{
        const r = await fetch(TELEMETRY_URL);
        if(r.ok){
          telemetry = await r.json();
          telemetryLive = true;
          const canSyncPresence = !presenceSyncedOnce || (performance.now() - presenceTouchedAt > 2500);
          if(canSyncPresence && typeof telemetry.presenceEnabled === "boolean"){
            presenceOn = telemetry.presenceEnabled;
            applyPresenceUi();
            presenceSyncedOnce = true;
          }
          const dt = performance.now() - t0;
          latencyAvg = latencyAvg * 0.82 + (telemetry.latencyMs || dt) * 0.18;
        }else{
          telemetryLive = false;
        }
      }catch(_){
        telemetryLive = false;
      }
    }
    async function pushVoice(){
      if(!micReady || micFreq < 30){ return; }
      const now = performance.now();
      if(now - lastVoicePost < 180){ return; }
      lastVoicePost = now;
      try{
        await fetch(VOICE_URL, {
          method:"POST",
          headers:{"Content-Type":"application/json"},
          body: JSON.stringify({voiceFreq: micFreq, voiceAmp: micAmp})
        });
      }catch(_){}
    }
    setInterval(pullTelemetry, 90);
    setInterval(pushVoice, 180);
    pullTelemetry().then(()=>applyPresenceUi());

    const navTabs = document.querySelectorAll(".nav-tab");
    const fieldControls = document.getElementById("fieldControls");
    const memoryPanel = document.getElementById("memoryPanel");
    const memoryPreview = document.getElementById("memoryPreview");
    const memoryMeta = document.getElementById("memoryMeta");
    const sessionList = document.getElementById("sessionList");
    const musicSelect = document.getElementById("musicSelect");
    const musicPlayBtn = document.getElementById("musicPlayBtn");
    const musicVol = document.getElementById("musicVol");
    const musicUpload = document.getElementById("musicUpload");
    const musicUploadBtn = document.getElementById("musicUploadBtn");
    const saveMemoryBtn = document.getElementById("saveMemory");
    let activeView = "garden";
    let musicCatalog = {builtin:[], files:[]};
    let selectedTrackId = "off";
    let musicPlaying = false;
    let musicCtx = null;
    let musicAnalyser = null;
    let musicGainNode = null;
    let musicElement = null;
    let musicMediaSrc = null;
    let musicSynthNodes = [];
    let musicAmp = 0;
    let musicFreq = 0;
    let musicData = null;
    let uploadObjectUrl = "";

    function setView(view){
      activeView = view;
      document.body.dataset.view = view;
      navTabs.forEach((tab)=>{
        const on = tab.dataset.view === view;
        tab.classList.toggle("is-active", on);
        tab.setAttribute("aria-selected", on ? "true" : "false");
      });
      const isGarden = view === "garden";
      fieldControls?.toggleAttribute("hidden", !isGarden);
      memoryPanel?.classList.toggle("is-open", view === "memory");
      memoryPanel?.toggleAttribute("hidden", view !== "memory");
      if(view === "memory"){ loadCompiledMemory(); renderSessions(); }
      setRenderSize();
    }
    navTabs.forEach((tab)=>{
      tab.addEventListener("click", ()=> setView(tab.dataset.view || "garden"));
    });
    document.body.dataset.view = "garden";

    function readSessions(){
      try{
        const raw = localStorage.getItem(SESSIONS_KEY);
        return raw ? JSON.parse(raw) : [];
      }catch(_){ return []; }
    }
    function writeSessions(items){
      localStorage.setItem(SESSIONS_KEY, JSON.stringify(items.slice(0, 24)));
    }
    function renderSessions(){
      if(!sessionList){ return; }
      const items = readSessions();
      sessionList.innerHTML = "";
      if(!items.length){
        sessionList.innerHTML = '<div class="memory-meta">No snapshots yet — use Save Memory in the dock.</div>';
        return;
      }
      for(const row of items){
        const el = document.createElement("div");
        el.className = "session-item";
        const left = document.createElement("span");
        left.textContent = row.label || row.id;
        const right = document.createElement("span");
        right.textContent = row.when || "";
        el.append(left, right);
        sessionList.appendChild(el);
      }
    }
    // 轻量 Markdown 渲染:标题/列表/粗体/代码,先 HTML 转义保证安全
    function escHtml(s){
      return s.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }
    function renderMemoryMd(text){
      const lines = escHtml(text || "").split(/\\r?\\n/);
      const out = [];
      let inList = false;
      const closeList = ()=>{ if(inList){ out.push("</ul>"); inList = false; } };
      for(const raw of lines){
        const line = raw.trimEnd();
        const h = line.match(/^(#{1,4})\\s+(.*)$/);
        const li = line.match(/^[-*]\\s+(.*)$/);
        if(h){
          closeList();
          const lvl = Math.min(4, h[1].length);
          out.push(`<div class="md-h md-h${lvl}">${h[2]}</div>`);
        }else if(li){
          if(!inList){ out.push('<ul class="md-ul">'); inList = true; }
          out.push(`<li>${li[1]}</li>`);
        }else if(line === ""){
          closeList();
          out.push('<div class="md-gap"></div>');
        }else{
          closeList();
          out.push(`<div class="md-p">${line}</div>`);
        }
      }
      closeList();
      return out.join("")
        .replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
    }
    function setMemoryContent(text){
      if(!memoryPreview){ return; }
      memoryPreview.innerHTML = renderMemoryMd(text);
    }
    async function loadCompiledMemory(){
      if(!memoryPreview){ return; }
      if(memoryMeta){ memoryMeta.textContent = "loading compiled memory…"; }
      try{
        const r = await fetch(MEMORY_COMPILED_URL);
        if(!r.ok){ throw new Error("memory " + r.status); }
        const data = await r.json();
        setMemoryContent(data.memory || "(empty MEMORY.md)");
        const names = (data.files || []).map((f)=>f.name).join(", ");
        if(memoryMeta){
          if(memoryMeta){
          memoryMeta.textContent = `${data.compiledDir || "knowledge/compiled"} · ${(data.files || []).length} files${names ? " · " + names : ""}`;
        }
        }
      }catch(err){
        memoryPreview.textContent = "Could not load compiled memory. Start Entry B on :8787 (repo Aster router). " + String(err);
        if(memoryMeta){ memoryMeta.textContent = "offline"; }
      }
    }
    async function compileMemory(){
      if(memoryMeta){ memoryMeta.textContent = "compiling…"; }
      try{
        const r = await fetch(MEMORY_COMPILE_URL, {method:"POST"});
        const data = await r.json();
        if(!r.ok || data.ok === false){
          throw new Error(data.error || ("compile " + r.status));
        }
        setMemoryContent(data.memory || "(empty)");
        const names = (data.files || []).map((f)=>f.name).join(", ");
        if(memoryMeta){ memoryMeta.textContent = `compiled · ${(data.files || []).length} files · ${names}`; }
      }catch(err){
        if(memoryMeta){ memoryMeta.textContent = "compile failed"; }
        memoryPreview.textContent = String(err);
      }
    }
    document.getElementById("memoryRefresh")?.addEventListener("click", loadCompiledMemory);
    document.getElementById("memoryCompile")?.addEventListener("click", compileMemory);

    function snapshotSession(){
      const id = `snap_${Date.now().toString(36)}`;
      const label = `session ${new Date().toLocaleString()}`;
      const row = {
        id,
        label,
        when: new Date().toISOString().slice(0, 19).replace("T", " "),
        controls: {...controls},
        presence: presenceOn,
        telemetry: {...telemetry},
        track: selectedTrackId,
      };
      const items = readSessions();
      items.unshift(row);
      writeSessions(items);
      renderSessions();
      return id;
    }
    saveMemoryBtn?.addEventListener("click", async ()=>{
      saveMemoryBtn.classList.add("is-busy");
      saveMemoryBtn.textContent = "Saving…";
      try{
        await compileMemory();
        const id = snapshotSession();
        saveMemoryBtn.textContent = "Saved";
        setTimeout(()=>{ saveMemoryBtn.textContent = "Save Memory"; }, 1400);
        if(activeView !== "memory"){ setView("memory"); }
        console.info("[Garden] memory snapshot", id);
      }catch(err){
        console.warn("[Garden] save memory", err);
        saveMemoryBtn.textContent = "Error";
        setTimeout(()=>{ saveMemoryBtn.textContent = "Save Memory"; }, 1600);
      }finally{
        saveMemoryBtn.classList.remove("is-busy");
      }
    });

    function stopMusicEngine(){
      musicPlaying = false;
      musicAmp = 0;
      musicFreq = 0;
      if(musicElement){
        musicElement.pause();
        musicElement.removeAttribute("src");
        musicElement.load();
      }
      for(const n of musicSynthNodes){
        try{
          if(n.stop){ n.stop(); }
          n.disconnect?.();
        }catch(_){}
      }
      musicSynthNodes = [];
      if(uploadObjectUrl){
        URL.revokeObjectURL(uploadObjectUrl);
        uploadObjectUrl = "";
      }
    }
    async function ensureMusicCtx(){
      if(!musicCtx){
        musicCtx = new (window.AudioContext || window.webkitAudioContext)();
        musicAnalyser = musicCtx.createAnalyser();
        musicAnalyser.fftSize = 2048;
        musicAnalyser.smoothingTimeConstant = 0.78;
        musicGainNode = musicCtx.createGain();
        musicGainNode.connect(musicAnalyser);
        musicAnalyser.connect(musicCtx.destination);
        musicData = new Uint8Array(musicAnalyser.frequencyBinCount);
      }
      if(musicCtx.state === "suspended"){ await musicCtx.resume(); }
      const vol = (parseFloat(musicVol?.value || "42") / 100) * 0.55;
      musicGainNode.gain.value = vol;
    }
    function trackById(id){
      const all = [...(musicCatalog.builtin || []), ...(musicCatalog.files || [])];
      return all.find((t)=>t.id === id) || null;
    }
    function allTracks(){
      return [...(musicCatalog.builtin || []), ...(musicCatalog.files || [])]
        .filter((t)=>t.type !== "synth" && !String(t.id || "").startsWith("gen_"));
    }
    function renderMusicDropdown(){
      if(!musicSelect){ return; }
      const tracks = allTracks();
      if(!tracks.some((t)=>t.id === selectedTrackId)){
        selectedTrackId = tracks[0]?.id || "off";
      }
      musicSelect.innerHTML = "";
      const addGroup = (label, items)=>{
        if(!items.length){ return; }
        const og = document.createElement("optgroup");
        og.label = label;
        for(const tr of items){
          const opt = document.createElement("option");
          opt.value = tr.id;
          const hint = tr.hint ? ` · ${tr.hint}` : (tr.filename ? ` · ${tr.filename}` : "");
          opt.textContent = (tr.label || tr.id) + hint;
          og.appendChild(opt);
        }
        musicSelect.appendChild(og);
      };
      addGroup("Background", tracks.filter((t)=>t.id === "off" || t.category === "background"));
      addGroup("Songs (local library)", tracks.filter((t)=>t.type === "file"));
      addGroup("Your uploads", tracks.filter((t)=>t.type === "upload"));
      if(!musicSelect.options.length){
        const opt = document.createElement("option");
        opt.value = "off";
        opt.textContent = "Off · add files or upload";
        musicSelect.appendChild(opt);
      }
      musicSelect.value = selectedTrackId;
    }
    function onMusicSelectionChanged(playNow){
      const id = musicSelect?.value || "off";
      selectedTrackId = id;
      try{ localStorage.setItem(MUSIC_PREF_KEY, id); }catch(_){}
      if(id === "off"){
        stopMusicEngine();
        updateMusicStatus();
        return;
      }
      if(playNow){ startSelectedTrack(); }
      else{ updateMusicStatus(); }
    }
    async function loadMusicCatalog(){
      try{
        const r = await fetch(MUSIC_CATALOG_URL);
        if(!r.ok){ throw new Error("catalog " + r.status); }
        musicCatalog = await r.json();
        musicCatalog.builtin = (musicCatalog.builtin || []).filter(
          (t)=>t.type !== "synth" && !String(t.id || "").startsWith("gen_")
        );
        musicCatalog.files = musicCatalog.files || [];
      }catch(err){
        console.warn("[Garden] music catalog", err);
        musicCatalog = {builtin:[{id:"off", label:"Off (mic only)", type:"none", category:"background"}], files:[]};
      }
      const saved = (()=>{ try{ return localStorage.getItem(MUSIC_PREF_KEY); }catch(_){ return null; }})();
      if(saved && allTracks().some((t)=>t.id === saved)){ selectedTrackId = saved; }
      else if(saved && (saved.startsWith("gen_") || saved !== "off")){ selectedTrackId = "off"; try{ localStorage.setItem(MUSIC_PREF_KEY,"off"); }catch(_){} }
      renderMusicDropdown();
      updateMusicStatus();
    }
    function updateMusicStatus(){
      const tr = trackById(selectedTrackId);
      const name = tr?.label || selectedTrackId;
      if(musicPlayBtn){
        musicPlayBtn.textContent = musicPlaying ? "Ⅱ" : "▶";
        musicPlayBtn.classList.toggle("is-on", musicPlaying);
        musicPlayBtn.title = musicPlaying ? `Pause · ${name}` : `Play · ${name}`;
      }
      if(musicSelect && tr){
        musicSelect.title = selectedTrackId === "off" ? "Mic only" : name;
      }
    }
    async function startSelectedTrack(){
      stopMusicEngine();
      const tr = trackById(selectedTrackId);
      if(!tr || tr.id === "off"){ updateMusicStatus(); return; }
      await ensureMusicCtx();
      if(tr.type === "file" || tr.type === "upload"){
        const url = tr.url || tr.objectUrl;
        if(!url){ return; }
        if(!musicElement){
          musicElement = new Audio();
          musicElement.crossOrigin = "anonymous";
          musicElement.loop = true;
          musicMediaSrc = musicCtx.createMediaElementSource(musicElement);
        }
        musicElement.src = url.startsWith("http") || url.startsWith("blob:") ? url : `${GARDEN_API}${url}`;
        try{ musicMediaSrc.disconnect(); }catch(_){}
        musicMediaSrc.connect(musicGainNode);
        await musicElement.play();
        musicPlaying = true;
      }
      updateMusicStatus();
    }
    musicSelect?.addEventListener("change", ()=> onMusicSelectionChanged(true));
    musicPlayBtn?.addEventListener("click", async ()=>{
      if(selectedTrackId === "off"){ return; }
      if(musicPlaying){ stopMusicEngine(); updateMusicStatus(); return; }
      await startSelectedTrack();
    });
    musicVol?.addEventListener("input", ()=>{
      if(musicGainNode){
        musicGainNode.gain.value = (parseFloat(musicVol.value || "42") / 100) * 0.55;
      }
    });
    musicUploadBtn?.addEventListener("click", ()=> musicUpload?.click());
    musicUpload?.addEventListener("change", ()=>{
      const file = musicUpload.files?.[0];
      if(!file){ return; }
      if(uploadObjectUrl){ URL.revokeObjectURL(uploadObjectUrl); }
      uploadObjectUrl = URL.createObjectURL(file);
      const id = "upload_local";
      const without = (musicCatalog.files || []).filter((t)=>t.id !== id);
      musicCatalog.files = [
        {id, label: file.name, type:"upload", category:"upload", objectUrl: uploadObjectUrl},
        ...without,
      ];
      selectedTrackId = id;
      renderMusicDropdown();
      if(musicSelect){ musicSelect.value = id; }
      musicUpload.value = "";
      startSelectedTrack();
    });
    loadMusicCatalog();

    function readMusicSpectrum(){
      if(!musicPlaying || !musicAnalyser || !musicData){ return {amp:0, freq:0}; }
      musicAnalyser.getByteFrequencyData(musicData);
      let sum = 0, peak = 0, peakI = 0;
      for(let i=0;i<musicData.length;i++){
        const v = musicData[i];
        sum += v;
        if(v > peak){ peak = v; peakI = i; }
      }
      const amp = Math.min(1, (sum / musicData.length) / 110);
      const binHz = (musicCtx?.sampleRate || 44100) / (musicAnalyser.fftSize || 2048);
      const freq = Math.max(80, peakI * binHz);
      musicAmp = amp;
      musicFreq = freq;
      return {amp, freq};
    }

    function drawSpectrum(){
      if(!specCanvas || !specCtx){ return; }
      const w = specCanvas.width;
      const h = specCanvas.height;
      specCtx.clearRect(0, 0, w, h);
      specCtx.fillStyle = "rgba(0,0,0,.18)";
      specCtx.fillRect(0, 0, w, h);
      if(!micReady || !micData){
        specCtx.fillStyle = "rgba(248,246,238,.28)";
        specCtx.font = "10px SF Mono, Menlo, monospace";
        specCtx.fillText("enable mic for live FFT", 12, h * 0.58);
        return;
      }
      // 对数频轴 80Hz-8kHz:线性刻度下语音能量全挤在最左几根条里,几乎不可见
      const bars = 48;
      const bw = w / bars;
      const nyqS = (micCtx?.sampleRate || 48000) / 2;
      const fLo = 80, fHi = Math.min(8000, nyqS);
      const logLo = Math.log(fLo), logSpan = Math.log(fHi) - logLo;
      const nBins = micData.length;
      for(let i=0;i<bars;i++){
        const f0 = Math.exp(logLo + logSpan * (i / bars));
        const f1 = Math.exp(logLo + logSpan * ((i + 1) / bars));
        const b0 = Math.max(0, Math.floor(f0 / nyqS * nBins));
        const b1 = Math.min(nBins - 1, Math.max(b0 + 1, Math.ceil(f1 / nyqS * nBins)));
        let mx = 0;
        for(let j=b0;j<b1;j++){ const v = micData[j]; if(v > mx){ mx = v; } }
        const v = Math.sqrt(mx / 255); // sqrt 曲线抬升低电平,小声说话也看得见
        // peak hold:峰值缓慢回落,视觉上更生动也更可读
        specPeaks[i] = Math.max(v, (specPeaks[i] || 0) - 0.012);
        const bh = Math.max(1, v * h * 0.92);
        const x = i * bw + 1;
        const y = h - bh;
        const g = specCtx.createLinearGradient(0, y, 0, h);
        g.addColorStop(0, "rgba(134,214,163,.95)");
        g.addColorStop(0.55, "rgba(119,216,216,.72)");
        g.addColorStop(1, "rgba(216,195,138,.35)");
        specCtx.fillStyle = g;
        specCtx.fillRect(x, y, Math.max(1, bw - 2), bh);
        const py = h - Math.max(1, specPeaks[i] * h * 0.92);
        specCtx.fillStyle = "rgba(255,215,120,.85)";
        specCtx.fillRect(x, py, Math.max(1, bw - 2), 1);
      }
    }

    function animateLayer(layer, ts, dtMs, amp, freq, gain, depthGain, driftX, coherence, micLow, micHigh, morph={radial:1, yPull:0, think:0, speak:0, listen:0}){
      const pos = layer.geo.attributes.position;
      const breathWave = Math.sin(ts * 0.00028) * (0.22 + micLow * 0.18) * (0.85 + amp * 0.35);
      const breathWave2 = Math.sin(ts * 0.00019 + 1.2) * 0.12 * (1.0 + amp * 0.25);
      const ripple = micHigh * Math.max(0, coherence) * 0.05;
      const loose = (1.0 - Math.max(0, coherence)) * 0.11;
      const radialScale = morph.radial ?? 1;
      const yPull = morph.yPull ?? 0;
      const inward = (morph.think || 0) * 0.34 + (morph.listen || 0) * 0.16;
      const outward = (morph.speak || 0) * 0.42;
      const flowMul = (1 - (morph.think || 0) * 0.38) * (1 + (morph.speak || 0) * 0.32);
      // 相位逐帧累积(修复:原 flowT = ts*0.00024*gain 在 gain 被状态/音频调制时,
      // 相位 = 绝对时间×增益会瞬间扫过几十弧度 → 整场抽搐"放鞭炮"。
      // 累积式下,gain 变化只改变此刻的转速,过去的相位是既成事实 —— 减速可见且丝滑)
      layer.flowPhase  = (layer.flowPhase  || 0) + dtMs * 0.00024 * gain * flowMul;
      layer.depthPhase = (layer.depthPhase || 0) + dtMs * 0.00062 * (freq / 260);
      const flowT = layer.flowPhase;
      const depthT = layer.depthPhase;
      for(let i=0;i<layer.count;i++){
        const idx=i*3;
        let bx=layer.base[idx]*controls.disp*radialScale + driftX;
        let by=layer.base[idx+1]*(1 - yPull*0.42);
        let bz=layer.base[idx+2]*radialScale;
        const ph=layer.phase[i];
        const radial = Math.sqrt(bx*bx + bz*bz);
        const radialN = radial * 0.009;
        const rNorm = Math.min(1, radial / 110);
        const pinch = inward * rNorm * radial * 0.0048;
        const bloom = outward * (1 - rNorm * 0.3) * radial * 0.0058;
        bx += -bx * pinch + bx * bloom * 0.2;
        bz += -bz * pinch + bz * bloom * 0.22;
        const swing = Math.sin(flowT + by*0.028 + ph) * 0.55 + Math.sin(flowT*1.37 + ph*0.6) * 0.28;
        const curl = Math.cos(flowT*0.88 + bx*0.034 + ph*0.45) * 0.48 + Math.sin(flowT*0.62 + by*0.02) * 0.22;
        const swirl = (morph.think || 0) * Math.sin(flowT*2.2 + ph + radialN*9) * 3.4;
        const drift = Math.sin(depthT + bx*0.05 + ph*0.35) * depthGain * controls.depthWave * 0.72;
        const tight = (1.0 - loose * 0.16) * (1 + (morph.think || 0) * 0.18);
        const flowX = swing * (0.55 + controls.flowAmp*0.95 + amp*1.15) + breathWave * bx * 0.008 + ripple * radialN * Math.sin(ph + ts*0.0011) + swirl;
        const flowY = curl * (0.32 + controls.dance*0.72 + amp*0.65) + (breathWave + breathWave2) * 0.42 + (morph.speak || 0) * Math.sin(flowT*1.7 + ph) * 0.72;
        pos.setXYZ(i,
          bx + flowX * tight,
          by + flowY * tight,
          bz + drift + ripple * radialN * 0.32
        );
      }
      pos.needsUpdate = true;
    }

    let frames=0,fps=0,t0=performance.now();
    function tick(ts){
      requestAnimationFrame(tick);
      try{
      if(micReady && micAnalyser && micData){
        micAnalyser.getByteFrequencyData(micData);
        let sum = 0;
        let low = 0;
        let mid = 0;
        let high = 0;
        const n = micData.length;
        for(let i=0;i<n;i++){
          const v = micData[i];
          sum += v;
          if(i < n*0.12){ low += v; }
          else if(i < n*0.4){ mid += v; }
          else { high += v; }
        }
        micAmp = sum / (n * 255);
        micLow = low / (Math.max(1,n*0.12) * 255);
        micMid = mid / (Math.max(1,n*0.28) * 255);
        micHigh = high / (Math.max(1,n*0.6) * 255);
        // 音高检测:只在人声基频段 80-600 Hz 内找峰,避免噪声/谐波把读数拽到几 kHz
        const nyq = (micCtx?.sampleRate || 48000) / 2;
        const binHz = nyq / Math.max(1, n - 1);
        const lo = Math.max(1, Math.floor(VOICE_BAND_LOW / binHz));
        const hi = Math.min(n - 2, Math.ceil(VOICE_BAND_HIGH / binHz));
        let vMax = 0, vI = -1;
        for(let i=lo;i<=hi;i++){
          const v = micData[i];
          if(v > vMax){ vMax = v; vI = i; }
        }
        // 能量门限:没有真实人声时不更新频率,防止 idle 状态挂着旧值
        if(vI > 0 && vMax >= VOICE_PEAK_GATE && micAmp >= VOICE_AMP_GATE){
          // 抛物线插值:分辨率从 binHz(~23Hz)提升到亚 bin 级
          const y0 = micData[vI-1], y1 = micData[vI], y2 = micData[vI+1];
          const denom = (y0 - 2*y1 + y2);
          const off = denom !== 0 ? 0.5 * (y0 - y2) / denom : 0;
          const rawHz = (vI + Math.max(-0.5, Math.min(0.5, off))) * binHz;
          micFreq = micFreq > 0 ? micFreq * 0.7 + rawHz * 0.3 : rawHz; // EMA 平滑
          micFreqAt = performance.now();
        }else if(performance.now() - micFreqAt > VOICE_HOLD_MS){
          micFreq = 0; // 过期清零:与后端 TTL 行为一致,显示层不再说谎
        }
      }else{
        micAmp *= 0.95;
        micLow *= 0.95;
        micMid *= 0.95;
        micHigh *= 0.95;
      }
      const teleAmp = telemetry.aiAmplitude || 0.12;
      const teleFreq = telemetry.aiFreq || 220;
      const musicSig = readMusicSpectrum();
      const useMusic = musicPlaying && musicSig.amp > 0.02;
      const blendAmp = useMusic ? Math.max(micAmp, musicSig.amp) : micAmp;
      const blendFreq = useMusic && musicSig.amp >= micAmp * 0.7 ? musicSig.freq : micFreq;
      const drive = computeParticleDrive(telemetry, micFreq, micReady, blendAmp, blendFreq);
      // ---- aiState 四态形变 ----
      // 目标状态:后端 aiState 优先;老后端无此字段时从 speaking/voiceSource 推导
      let aiStateRaw = telemetry.aiState
        || (telemetry.speaking ? "speaking" : (telemetry.voiceSource === "mic" ? "listening" : "idle"));
      if(morphDemoOn){
        const demoPhase = Math.floor((ts - morphDemoT) / 2200) % 4;
        aiStateRaw = ["idle","listening","thinking","speaking"][demoPhase];
        if(ts - morphDemoT > 8800){ morphDemoOn = false; }
      }
      // thinking 锁存:合成可能只有几百毫秒,保证形变至少完整呈现 900ms
      if(aiStateRaw === "thinking"){ thinkingLatchT = ts; }
      else if(ts - thinkingLatchT < THINKING_MIN_MS && thinkingLatchT > 0 && aiStateRaw !== "speaking"){
        aiStateRaw = "thinking"; // speaking 可以打断锁存(声音已经出来了)
      }
      displayedState = aiStateRaw;
      const dtState = lastStateTs > 0 ? Math.min(0.1, (ts - lastStateTs) / 1000) : 0.016;
      const dtMs = dtState * 1000;
      lastStateTs = ts;
      // 不对称呼吸节奏:吸气慢(进入 thinking ~700ms),呼出快(thinking→speaking ~170ms)。
      // 对称的 220ms 是 UI 动效的时间常数,不是身体的 —— 活物的收与放不等速。
      for(const s of ["idle","listening","thinking","speaking"]){
        const target = (aiStateRaw === s) ? 1 : 0;
        let rate = 3.0;
        if(s === "thinking") rate = target > stateW[s] ? 1.5 : 6.0;   // 慢收,快放
        if(s === "speaking") rate = target > stateW[s] ? 6.0 : 2.2;   // 涌出要果断,退潮可以慢
        stateW[s] += (target - stateW[s]) * (1 - Math.exp(-dtState * rate));
      }
      // thinking:场向内收缩、变暗、缓慢盘旋 —— 像吸气屏息
      swirlPhase += dtState * stateW.thinking * 4.2;
      const contractF = 1 - stateW.thinking * 0.72;
      const dimF = 1 - stateW.thinking * 0.52;
      // listening:聚拢侧耳
      const leanF = 1 + stateW.listening * 0.38;
      // speaking:场舒张涌出 —— thinking 的收缩在此释放
      const expandF = 1 + stateW.speaking * 0.55;
      // 几何:group scale + 顶点 radial 双通道,否则只有 15% 肉眼几乎看不见
      const fieldScale = 1 - stateW.thinking * 0.34 + stateW.speaking * 0.30 + stateW.listening * 0.06;
      const radialScale = 1 - stateW.thinking * 0.58 + stateW.speaking * 0.72 + stateW.listening * 0.22;
      const yPull = stateW.thinking * 0.68 - stateW.speaking * 0.52 + stateW.listening * 0.14;
      const sizeMul = 1 - stateW.thinking * 0.38 + stateW.speaking * 0.42 + stateW.listening * 0.14;
      const thinkTilt = Math.sin(ts * 0.0022) * stateW.thinking * 0.32;
      const speakPulse = Math.sin(ts * 0.0046) * stateW.speaking * 7.2;
      const listenGather = Math.sin(ts * 0.0015) * stateW.listening * 2.8;
      const layerMorph = {
        radial: radialScale, yPull, think: stateW.thinking, speak: stateW.speaking, listen: stateW.listening
      };
      const groupY = stateW.thinking * -16 + stateW.speaking * 12 + stateW.listening * -4;
      const stateDriftX = -stateW.listening * 4.2 + stateW.speaking * 3.0 - stateW.thinking * 2.4;
      const amp = drive.amp;
      const glow = (0.92 + amp * 0.18) * dimF * (1 + stateW.listening * 0.22 + stateW.speaking * 0.38 - stateW.thinking * 0.1);
      const freq = drive.freq;
      const gain = controls.flow * (1.1 + amp*2.2 + drive.coherence*0.35) * contractF * leanF * expandF;
      const depthGain = controls.depth * (18 + amp*28 + drive.energy*12) * contractF * expandF;
      const voiceBoost = 1.0 + micAmp * 2.4 + drive.coherence * 0.6;
      const fieldCoh = drive.coherence > 0 ? drive.coherence : 0;
      // 拍频呼吸:|f_voice - f_ai| 是两个声音叠加的物理脉动频率。
      // 失配 → 场以拍频颤动(对不上的感觉是涌现的,不是装饰的);
      // 逼近 → 颤动放缓变深;对齐 → 颤动消失,只剩一口深长的共同呼吸。
      // 调音语义只对纯音 echo 成立:语音(macos_say/kokoro)不是单音,
      // 过零频率会撞 900Hz 钳位,beat 满格 12Hz → 场狂抖"放鞭炮"。
      const tuningMode = telemetry.aiSource === "presence_echo";
      let beatHz = 0;
      if(tuningMode && drive.voiceHz > 30 && drive.aiHz > 30){
        beatHz = Math.min(12, Math.abs(drive.voiceHz - drive.aiHz));
      }
      lastBeatHz = beatHz;
      const misalign = 1 - fieldCoh;
      // 颤动幅度随拍频衰减:快拍读作细微闪烁,慢拍才是可见的脉动 —— 接近真实拍频的听感
      const tremorAmp = 1.1 / (1 + beatHz * 0.22);
      const tremor = (tuningMode && beatHz > 0.05)
        ? Math.sin(ts * 0.001 * beatHz * 6.28318) * misalign * tremorAmp
        : 0;
      const cohBoost = tuningMode ? fieldCoh * 0.9 : 0; // 对齐呼吸也只属于调音时刻
      const alignedBreath = Math.sin(ts*0.00022) * (1.4 + amp*2.8) * (1 + cohBoost);
      const fieldBreath = (alignedBreath + tremor + speakPulse + listenGather) * contractF;
      animateLayer(core, ts, dtMs, amp, freq, gain*voiceBoost, depthGain*1.2, -30.0 + fieldBreath + stateDriftX, fieldCoh, micLow, micHigh, layerMorph);
      animateLayer(halo, ts, dtMs, amp, freq, gain*1.08*voiceBoost, depthGain*1.35, -30.0 + fieldBreath + stateDriftX, fieldCoh, micLow, micHigh, layerMorph);
      animateLayer(fringeGreen, ts, dtMs, amp, freq, gain*1.15*voiceBoost, depthGain*1.45, -29.2 + fieldBreath + stateDriftX, fieldCoh, micLow, micHigh, layerMorph);
      animateLayer(fringeCyan, ts, dtMs, amp, freq, gain*1.22*voiceBoost, depthGain*1.55, -30.8 + fieldBreath + stateDriftX, fieldCoh, micLow, micHigh, layerMorph);
      animateLayer(fringeCoral, ts, dtMs, amp, freq, gain*1.08*voiceBoost, depthGain*1.4, -29.5 + fieldBreath + stateDriftX, fieldCoh, micLow, micHigh, layerMorph);
      animateLayer(dust, ts, dtMs, amp, freq, gain*0.88, depthGain*1.85, -33.0 + fieldBreath*0.7, fieldCoh, micLow, micHigh, {...layerMorph, radial: radialScale*0.9, yPull: yPull*0.65});

      // 几何呼吸:边缘先于核心收 —— 吸气从外向内
      pCore.scale.setScalar(fieldScale);
      pHalo.scale.setScalar(fieldScale * (1 - stateW.thinking * 0.04 + stateW.speaking * 0.03));
      pGreen.scale.setScalar(fieldScale * (1 - stateW.thinking * 0.06));
      pCyan.scale.setScalar(fieldScale * (1 - stateW.thinking * 0.05 + stateW.speaking * 0.04));
      pCoral.scale.setScalar(fieldScale * (1 - stateW.thinking * 0.04 + stateW.speaking * 0.02));
      pDust.scale.setScalar(fieldScale * (1 - stateW.thinking * 0.12 + stateW.speaking * 0.02));
      pCore.position.y = groupY;
      pHalo.position.y = groupY * 0.92;
      pGreen.position.y = groupY * 0.88;
      pCyan.position.y = groupY * 0.95;
      pCoral.position.y = groupY * 0.9;
      pDust.position.y = groupY * 0.5;

      pCore.rotation.y = Math.sin(ts*0.00011)*0.24 + swirlPhase;
      pHalo.rotation.y = Math.sin(ts*0.000105)*0.26 + swirlPhase * 0.92;
      pGreen.rotation.y = Math.sin(ts*0.000102)*0.29 + swirlPhase * 1.08;
      pCyan.rotation.y = Math.sin(ts*0.000098)*0.31 + swirlPhase * 1.15;
      pCoral.rotation.y = Math.sin(ts*0.000106)*0.27 + swirlPhase * 0.85;
      pDust.rotation.y = Math.sin(ts*0.00008)*0.34 + swirlPhase * 1.3;
      pDust.rotation.z = Math.cos(ts*0.00012)*0.05 + thinkTilt;
      pCore.rotation.x = thinkTilt * 0.75;
      pHalo.rotation.x = thinkTilt * 0.55;

      const shift = ts*0.0006*controls.colorShift;
      const tSec = ts * 0.001;
      for(const mat of particleMats){ mat.uniforms.uTime.value = tSec; }
      mCore.uniforms.uSize.value = controls.size * 0.95 * sizeMul;
      mHalo.uniforms.uSize.value = controls.size * 1.22 * sizeMul;
      mGreen.uniforms.uSize.value = controls.size * 1.05 * sizeMul;
      mCyan.uniforms.uSize.value = controls.size * 1.08 * sizeMul;
      mCoral.uniforms.uSize.value = controls.size * 0.98 * sizeMul;
      mDust.uniforms.uSize.value = controls.size * 0.52 * sizeMul;
      mCore.uniforms.uAmp.value = glow * controls.contrast * 1.18;
      mHalo.uniforms.uAmp.value = glow * controls.contrast * 1.05;
      mGreen.uniforms.uAmp.value = glow * controls.contrast * 1.55;
      mCyan.uniforms.uAmp.value = glow * controls.contrast * 2.45;
      mCoral.uniforms.uAmp.value = glow * controls.contrast * 1.28;
      mDust.uniforms.uAmp.value = glow * controls.contrast * 0.62;
      mHalo.uniforms.uShift.value = shift * 0.45;
      mGreen.uniforms.uShift.value = shift * 0.8;
      mCyan.uniforms.uShift.value = shift;
      mCoral.uniforms.uShift.value = shift * 1.2;
      mDust.uniforms.uShift.value = shift * 0.7;

      const mx = mouseX * controls.mouse * 0.006;
      const my = mouseY * controls.mouse * 0.008;
      const plumeOffset = FIGURE_X + (controls.disp - 1.4) * 10.0;
      pCore.position.x = plumeOffset;
      pHalo.position.x = plumeOffset;
      pGreen.position.x = plumeOffset - 5;
      pCoral.position.x = plumeOffset - 3;
      pCyan.position.x = plumeOffset + 4;
      pDust.position.x = plumeOffset;
      renderer.toneMappingExposure = 2.92 * dimF * (1 + stateW.speaking * 0.42 - stateW.thinking * 0.22 + stateW.listening * 0.08);
      const aimX = VIEW_AIM_X + mx * 0.18 + stateW.listening * 2.8 - stateW.thinking * 2.2 + stateW.speaking * 1.0;
      const camZBase = 98 + Math.sin(ts*0.00009*(0.6 + controls.depth*0.8)) * (5 + controls.depth*7);
      const camZTarget = camZBase - stateW.thinking * 52 + stateW.speaking * 44 - stateW.listening * 12;
      const fovTarget = (50 - controls.depth*5.5) - stateW.thinking * 9 + stateW.speaking * 10 + stateW.listening * 2;
      camera.position.x += (aimX - camera.position.x) * (0.05 + stateW.thinking * 0.05);
      camera.position.y += ((my*0.35) - camera.position.y) * 0.03 + stateW.thinking * 1.2 - stateW.speaking * 0.5;
      camera.position.z += (camZTarget - camera.position.z) * (0.09 + stateW.thinking * 0.07 + stateW.speaking * 0.05);
      camera.fov += (fovTarget - camera.fov) * 0.08;
      camera.updateProjectionMatrix();
      camera.lookAt(aimX, 4, 0);
      renderer.render(scene,camera);

      frames++; if(ts-t0>500){fps=Math.round(frames*1000/(ts-t0));frames=0;t0=ts;}
      const elapsed = Math.max(0, Math.floor((performance.now() - timerT0) / 1000));
      const hh = String(Math.floor(elapsed / 3600)).padStart(2, "0");
      const mm = String(Math.floor((elapsed % 3600) / 60)).padStart(2, "0");
      const ss = String(elapsed % 60).padStart(2, "0");
      const telLabel = telemetryLive ? (telemetry.active ? "live" : "idle") : "offline";
      hud.textContent =
        `session ${hh}:${mm}:${ss}\n` +
        substrateHudLines.join("\n") + "\n" +
        `telemetry ${telLabel}\n` +
        `fps ${fps}\n` +
        `latency ~${latencyAvg.toFixed(0)} ms\n` +
        `particles ${PARTICLE_COUNT}\n` +
        `state ${displayedState} (t${stateW.thinking.toFixed(2)} s${stateW.speaking.toFixed(2)} l${stateW.listening.toFixed(2)})\n` +
        `coh ${drive.coherence > 0 ? drive.coherence.toFixed(3) : "—"}`;

      if(aVoice){
        aVoice.textContent = drive.hasMic || drive.voiceHz > 0
          ? `${drive.voiceHz.toFixed(0)} Hz (${telemetry.voiceSource || "mic"})`
          : "— (mic off)";
        aVoice.className = "v " + (micReady ? "live" : "stub");
      }
      if(aAi){
        aAi.textContent = drive.aiActive
          ? `${drive.aiHz.toFixed(0)} Hz · ${telemetry.aiSource || "echo"} · amp ${drive.aiAmplitude.toFixed(2)}`
          : "— (idle)";
        aAi.className = "v " + (drive.aiActive ? "live" : "stub");
      }
      if(aCoh){ aCoh.textContent = drive.coherence > 0 ? drive.coherence.toFixed(3) : "—"; }
      if(aState){
        aState.textContent = displayedState;
        aState.className = "v state-" + displayedState;
      }
      if(fieldVignette){
        fieldVignette.classList.toggle("is-thinking", stateW.thinking > 0.06);
        fieldVignette.classList.toggle("is-speaking", stateW.speaking > 0.06);
        fieldVignette.classList.toggle("is-listening",
          stateW.listening > 0.22 && stateW.thinking < 0.12 && stateW.speaking < 0.12);
      }
      if(stateBadge){
        const dominant = stateW.thinking >= stateW.speaking && stateW.thinking >= stateW.listening && stateW.thinking > 0.06
          ? "thinking"
          : (stateW.speaking >= stateW.listening && stateW.speaking > 0.06
            ? "speaking"
            : (stateW.listening > 0.22 ? "listening" : ""));
        stateBadge.textContent = dominant ? dominant : "";
        stateBadge.className = "state-badge" + (dominant ? ` is-on ${dominant}` : "");
      }
      if(aBeat){
        const tuning = telemetry.aiSource === "presence_echo";
        const inSync = tuning && drive.coherence > 0.9 && lastBeatHz < 0.8;
        aBeat.textContent = !tuning
          ? "\u2014 (echo only)"
          : (drive.voiceHz > 30 && drive.aiHz > 30)
            ? (inSync ? "in sync \u2726" : lastBeatHz.toFixed(1) + " Hz")
            : "\u2014";
        aBeat.className = "v " + (inSync ? "live" : "stub");
      }
      if(aEnergy){ aEnergy.textContent = (drive.hasMic || drive.aiActive) ? drive.energy.toFixed(3) : "—"; }
      if(cohFill){
        cohFill.style.width = drive.coherence > 0 ? `${Math.min(100, drive.coherence * 100).toFixed(1)}%` : "0%";
      }
      analysis?.classList.toggle("is-live", !!(drive.hasMic || drive.aiActive));
      if(bLow){ bLow.style.width = `${Math.min(100, micLow * 100).toFixed(1)}%`; }
      if(bMid){ bMid.style.width = `${Math.min(100, micMid * 100).toFixed(1)}%`; }
      if(bHigh){ bHigh.style.width = `${Math.min(100, micHigh * 100).toFixed(1)}%`; }
      drawSpectrum();
      }catch(err){
        console.error("[Garden] tick", err);
      }
    }
    requestAnimationFrame(()=>{
      setRenderSize();
      requestAnimationFrame(tick);
    });
  </script>
</body>
</html>
"""


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/memory/compiled")
async def memory_compiled() -> dict:
    from scripts.garden_services import compiled_memory_payload

    return compiled_memory_payload()


@app.post("/api/memory/compile")
async def memory_compile() -> dict:
    from scripts.garden_services import run_memory_compile

    return run_memory_compile()


@app.get("/api/music/catalog")
async def music_list() -> dict:
    return music_catalog()


@app.get("/assets/music/{filename}")
async def music_asset(filename: str) -> FileResponse:
    path = resolve_music_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="track not found")
    return FileResponse(path)


@app.get("/", response_class=HTMLResponse)
async def root() -> str:
    return HTMLResponse(
        content=HTML,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )
