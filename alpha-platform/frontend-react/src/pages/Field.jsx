import React, { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { useStream } from '../ws.js'

// 粒子场 v0.6 — 每标的一簇轨道粒子:簇半径=波动 · 轨速=动量 · 色=方向
// 休市/无数据时进入金色环流待机态,不再出现死方块
const UP = new THREE.Color('#4ADE80'), DOWN = new THREE.Color('#F87171'), IDLE = new THREE.Color('#E8B45A')
const PER = 520

function softSprite() {
  const cv = document.createElement('canvas'); cv.width = cv.height = 64
  const g = cv.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32)
  gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.35, 'rgba(255,255,255,.55)'); gr.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = gr; g.fillRect(0, 0, 64, 64)
  return new THREE.CanvasTexture(cv)
}

export default function Field() {
  const mountRef = useRef(null)
  const stRef = useRef({ clusters: [] })
  const [legend, setLegend] = useState([])
  const snap = useStream()

  useEffect(() => {
    const el = mountRef.current
    const scene = new THREE.Scene()
    scene.fog = new THREE.FogExp2(0x0a0d13, 0.045)
    const camera = new THREE.PerspectiveCamera(50, el.clientWidth / 460, 0.1, 100)
    camera.position.set(0, 3.4, 11)
    camera.lookAt(0, 0, 0)
    const renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true })
    renderer.setSize(el.clientWidth, 460)
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2))
    el.appendChild(renderer.domElement)

    const st = stRef.current
    st.geo = new THREE.BufferGeometry()
    st.max = 40 * PER
    st.pos = new Float32Array(st.max * 3)
    st.col = new Float32Array(st.max * 3)
    st.geo.setAttribute('position', new THREE.BufferAttribute(st.pos, 3))
    st.geo.setAttribute('color', new THREE.BufferAttribute(st.col, 3))
    st.points = new THREE.Points(st.geo, new THREE.PointsMaterial({
      size: 0.14, map: softSprite(), vertexColors: true, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0.9,
    }))
    scene.add(st.points)

    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches
    let raf, t = 0
    const tick = () => {
      t += reduced ? 0 : 0.016
      const cs = st.clusters.length ? st.clusters
        : [{ cx: 0, cz: 0, r: 3.4, speed: 0.12, color: IDLE, n: 2200, phase: 0 }]
      let i = 0
      for (const c of cs) {
        for (let k = 0; k < c.n && i < st.max; k++, i++) {
          const a = c.phase + k * 2.399963 + t * c.speed
          const rr = c.r * (0.55 + 0.45 * Math.sin(k * 12.9898))
          const y = Math.sin(k * 78.233 + t * 0.7) * c.r * 0.22
          st.pos[i * 3] = c.cx + Math.cos(a) * rr
          st.pos[i * 3 + 1] = y
          st.pos[i * 3 + 2] = c.cz + Math.sin(a) * rr * 0.6
          st.col[i * 3] = c.color.r; st.col[i * 3 + 1] = c.color.g; st.col[i * 3 + 2] = c.color.b
        }
      }
      st.geo.setDrawRange(0, i)
      st.geo.attributes.position.needsUpdate = true
      st.geo.attributes.color.needsUpdate = true
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    }
    tick()
    const ro = new ResizeObserver(() => {
      camera.aspect = el.clientWidth / 460; camera.updateProjectionMatrix()
      renderer.setSize(el.clientWidth, 460)
    })
    ro.observe(el)
    return () => { cancelAnimationFrame(raf); ro.disconnect(); renderer.dispose(); el.innerHTML = '' }
  }, [])

  useEffect(() => {
    if (!snap) return
    const rows = [
      ...snap.pulse.equity.map(e => ({ sym: e.symbol, dir: e.factors?.ret_5m || 0, mag: Math.abs(e.factors?.vol_1m || 0) })),
      ...snap.pulse.crypto.map(c => ({ sym: c.symbol, dir: 0, mag: 0.0008 })),
    ].slice(0, 40)
    const cols = Math.ceil(Math.sqrt(rows.length || 1))
    stRef.current.clusters = rows.map((r, i) => ({
      cx: (i % cols - (cols - 1) / 2) * 3.1,
      cz: (Math.floor(i / cols) - (Math.ceil(rows.length / cols) - 1) / 2) * 2.6,
      r: 0.55 + Math.min(1.4, r.mag * 420),
      speed: Math.max(-1.6, Math.min(1.6, r.dir * 260)) + 0.08,
      color: r.dir > 0.0002 ? UP : r.dir < -0.0002 ? DOWN : IDLE,
      n: PER, phase: i * 1.7,
    }))
    setLegend(rows)
  }, [snap])

  return (<section className="glass">
    <h2>粒子场 v0.6 · 簇半径=波动 · 轨速=动量 · 色=方向</h2>
    <div ref={mountRef} style={{ margin: '8px 0' }} />
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px' }}>
      {legend.length ? legend.map(r =>
        <span key={r.sym} className="dim" style={{ fontSize: 11 }}>
          <i style={{ display: 'inline-block', width: 7, height: 7, borderRadius: 4, marginRight: 5,
            background: r.dir > 0.0002 ? '#4ADE80' : r.dir < -0.0002 ? '#F87171' : '#E8B45A' }} />
          {r.sym}</span>)
        : <span className="dim" style={{ fontSize: 11 }}>待机环流 · 等待市场脉搏(休市或首个采集周期)</span>}
    </div>
  </section>)
}
