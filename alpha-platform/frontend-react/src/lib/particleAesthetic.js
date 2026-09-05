import * as THREE from 'three'

/** 8787 Garden / Aster Field 视觉宪法 — 青紫雾、additive 光点、深空底 */
export const BG = 0x0a0a0f
export const BG_GRAD = '#0a0a0f'
export const GARDEN = {
  cyan: new THREE.Color('#8fd0e8'),
  slate: new THREE.Color('#7a8fb8'),
  perilla: new THREE.Color('#a78be0'),
  dew: new THREE.Color('#c8cad8'),
  gold: new THREE.Color('#e8c98a'),
  seal: new THREE.Color('#4ade80'),
  warn: new THREE.Color('#f87171'),
}
export const UP = GARDEN.seal.clone()
export const DOWN = GARDEN.warn.clone()
export const IDLE = GARDEN.gold.clone()

let spriteTex
export function softSprite() {
  if (spriteTex) return spriteTex
  const cv = document.createElement('canvas')
  cv.width = cv.height = 128
  const g = cv.getContext('2d')
  const gr = g.createRadialGradient(64, 64, 0, 64, 64, 64)
  gr.addColorStop(0, 'rgba(255,255,255,1)')
  gr.addColorStop(0.22, 'rgba(255,255,255,.72)')
  gr.addColorStop(0.55, 'rgba(200,220,255,.28)')
  gr.addColorStop(1, 'rgba(255,255,255,0)')
  g.fillStyle = gr
  g.fillRect(0, 0, 128, 128)
  spriteTex = new THREE.CanvasTexture(cv)
  spriteTex.needsUpdate = true
  return spriteTex
}

export function gardenHue(seed, t = 0) {
  const hue = (seed * 0.173 + t * 0.02) % 1
  const c1 = new THREE.Color('#8ca4c8')
  const c2 = new THREE.Color('#73b8c2')
  const c3 = new THREE.Color('#9488bc')
  return c1.clone().lerp(c2, hue).lerp(c3, Math.max(0, hue - 0.35) / 0.5)
}

export function dirColor(dir, mag = 0) {
  if (dir > 0.0002) return UP.clone().lerp(GARDEN.cyan, 0.35)
  if (dir < -0.0002) return DOWN.clone().lerp(GARDEN.perilla, 0.2)
  if (mag > 0) return IDLE.clone().lerp(GARDEN.slate, 0.25)
  return gardenHue(Math.abs(dir) * 1000 + 0.5)
}
