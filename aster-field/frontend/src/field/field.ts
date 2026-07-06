import * as THREE from 'three';
import { VERT, FRAG } from './shaders';
import { TOKENS } from '../tokens';
import { W_OF, type FieldState } from '../state/machine';

export class Field {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private U: Record<string, THREE.IUniform>;
  private target = new THREE.Vector4(1, 0, 0, 0);
  private clock = new THREE.Clock();
  private ripIdx = 0;
  private reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  private running = true;
  private brightTarget = 0;
  private raf = 0;
  private loopStarted = false;
  onFps: (fps: number) => void = () => {};

  constructor(canvas: HTMLCanvasElement) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.setSize(innerWidth, innerHeight);
    this.camera = new THREE.PerspectiveCamera(TOKENS.camera.fov, innerWidth / innerHeight, 0.1, 200);
    this.camera.position.set(0, TOKENS.camera.y, TOKENS.camera.z);

    const N = innerWidth < 640 ? TOKENS.particles.mobile : TOKENS.particles.desktop;
    const pos = new Float32Array(N * 3), seed = new Float32Array(N), shell = new Float32Array(N);
    const GA = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < N; i++) {
      const r = 8.5 * Math.cbrt(i / N) * (0.92 + Math.random() * 0.16);
      const y = 1 - (i / (N - 1)) * 2, rad = Math.sqrt(1 - y * y), th = GA * i;
      pos[i * 3] = Math.cos(th) * rad * r; pos[i * 3 + 1] = y * r * 0.86; pos[i * 3 + 2] = Math.sin(th) * rad * r;
      seed[i] = Math.random() * 1000; shell[i] = r / 8.5;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('seed', new THREE.BufferAttribute(seed, 1));
    geo.setAttribute('shell', new THREE.BufferAttribute(shell, 1));

    this.U = {
      uT: { value: 0 }, uPx: { value: this.renderer.getPixelRatio() },
      uW: { value: new THREE.Vector4(1, 0, 0, 0) }, uCoh: { value: 0.72 },
      uRip: { value: new THREE.Vector3(-99, -99, -99) },
      uMouse: { value: new THREE.Vector3(999, 0, 0) }, uFreeze: { value: 0 },
      uBright: { value: 0 },
    };
    const mat = new THREE.ShaderMaterial({ uniforms: this.U, transparent: true,
      depthWrite: false, blending: THREE.AdditiveBlending, vertexShader: VERT, fragmentShader: FRAG });
    this.scene.add(new THREE.Points(geo, mat));
    this.bindPointer();
    addEventListener('resize', () => {
      this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
      this.U.uPx.value = this.renderer.getPixelRatio();
      this.camera.aspect = innerWidth / innerHeight;
      this.camera.updateProjectionMatrix();
      this.renderer.setSize(innerWidth, innerHeight);
    });
    document.addEventListener('visibilitychange', () => {
      this.running = document.visibilityState === 'visible';
    });
    (document.getElementById('hN') as HTMLElement).textContent = N.toLocaleString();
  }

  setPresenceBoost(on: boolean): void { this.brightTarget = on ? 0.08 : 0; }

  setState(s: FieldState): void {
    if (s === 'error') { this.U.uFreeze.value = 1; setTimeout(() => (this.U.uFreeze.value = 0), 500); }
    this.target.fromArray(W_OF[s] ?? W_OF.idle);
  }
  setCoherence(v: number): void { this.U.uCoh.value = v; }
  ripple(): void {
    const u = this.U.uRip.value as THREE.Vector3;
    const v = [u.x, u.y, u.z]; v[this.ripIdx++ % 3] = this.clock.getElapsedTime();
    u.set(v[0], v[1], v[2]);
  }
  private bindPointer(): void {
    const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(),
      plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), hit = new THREE.Vector3();
    addEventListener('pointermove', (e) => {
      ndc.set((e.clientX / innerWidth) * 2 - 1, -(e.clientY / innerHeight) * 2 + 1);
      ray.setFromCamera(ndc, this.camera);
      if (ray.ray.intersectPlane(plane, hit)) (this.U.uMouse.value as THREE.Vector3).copy(hit);
    });
  }
  start(): void {
    if (this.loopStarted) return;
    this.loopStarted = true;
    let fpsT = 0, fpsN = 0;
    const loop = () => {
      this.raf = requestAnimationFrame(loop);
      if (!this.running) return;
      const dt = this.clock.getDelta(), t = this.clock.getElapsedTime();
      this.U.uT.value = this.reduced ? 8 : t;
      (this.U.uW.value as THREE.Vector4).lerp(this.target, 1 - Math.pow(0.0025, dt));
      const b = this.U.uBright.value as number;
      this.U.uBright.value = b + (this.brightTarget - b) * (1 - Math.pow(0.08, dt));
      const mx = (this.U.uMouse.value as THREE.Vector3).x;
      this.camera.position.x += (mx * 0.04 - this.camera.position.x) * 0.02;
      this.camera.lookAt(0, 0, 0);
      this.renderer.render(this.scene, this.camera);
      fpsN++; if (t - fpsT > 1) { this.onFps(fpsN); fpsN = 0; fpsT = t; }
    };
    loop();
  }
}
