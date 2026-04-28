import './style.css';
import { MicAudio } from './core/audio';
import { computeParticleDrive, type TelemetrySample } from './core/controller';
import { ParticleRenderer } from './core/renderer';
import { createHud } from './ui/hud';
import { createParamsPanel, type Tunables } from './ui/params';

const TELEMETRY_URL = '/api/telemetry';

let telemetry: TelemetrySample = {
  t: 0,
  voiceFreq: 220,
  aiFreq: 260,
  aiAmplitude: 0.2,
  latencyMs: 24,
};

async function fetchTelemetry(): Promise<void> {
  const t0 = performance.now();
  try {
    const r = await fetch(TELEMETRY_URL, { cache: 'no-store' });
    const dt = performance.now() - t0;
    if (!r.ok) throw new Error(String(r.status));
    const j = (await r.json()) as Partial<TelemetrySample>;
    telemetry = {
      t: typeof j.t === 'number' ? j.t : performance.now() / 1000,
      voiceFreq: typeof j.voiceFreq === 'number' ? j.voiceFreq : telemetry.voiceFreq,
      aiFreq: typeof j.aiFreq === 'number' ? j.aiFreq : telemetry.aiFreq,
      aiAmplitude: typeof j.aiAmplitude === 'number' ? j.aiAmplitude : telemetry.aiAmplitude,
      latencyMs: typeof j.latencyMs === 'number' ? j.latencyMs : dt,
    };
  } catch {
    const t = performance.now() / 1000;
    telemetry = {
      t,
      voiceFreq: 200 + 80 * Math.sin(t * 1.1),
      aiFreq: 200 + 80 * Math.cos(t * 0.9),
      aiAmplitude: 0.15 + 0.08 * Math.sin(t * 1.7) ** 2,
      latencyMs: performance.now() - t0,
    };
  }
}

function main(): void {
  const canvas = document.querySelector<HTMLCanvasElement>('#c');
  const hudRoot = document.querySelector<HTMLElement>('#hud');
  const guiMount = document.querySelector<HTMLElement>('#gui');
  if (!canvas || !hudRoot || !guiMount) throw new Error('Missing DOM nodes');

  const tunables: Tunables = {
    particleCount: 100_000,
    dispersion: 1.45,
    micOn: false,
  };

  const mic = new MicAudio();
  const particles = new ParticleRenderer(canvas, {
    particleCount: tunables.particleCount,
    dispersion: tunables.dispersion,
  });

  const hud = createHud(hudRoot);
  const { setMicGui } = createParamsPanel(guiMount, tunables, {
    onParticleCount(n) {
      tunables.particleCount = n;
      particles.setParticleCount(n);
    },
    onDispersion(d) {
      tunables.dispersion = d;
      particles.setDispersion(d);
    },
    onMicToggle(on) {
      tunables.micOn = on;
      void (async () => {
        if (on) {
          try {
            await mic.start();
          } catch {
            tunables.micOn = false;
            setMicGui(false);
          }
        } else {
          mic.stop();
        }
      })();
    },
  });

  void fetchTelemetry();
  setInterval(() => void fetchTelemetry(), 80);

  let frames = 0;
  let fps = 0;
  let fpsT = performance.now();
  const latRing: number[] = [];

  const onResize = (): void => {
    const w = window.innerWidth;
    const h = window.innerHeight;
    particles.setSize(w, h);
  };
  onResize();
  window.addEventListener('resize', onResize);

  function loop(): void {
    requestAnimationFrame(loop);
    const now = performance.now();
    frames++;
    if (now - fpsT >= 400) {
      fps = (frames / (now - fpsT)) * 1000;
      frames = 0;
      fpsT = now;
    }

    const voiceHzMic = mic.isRunning() ? mic.getVoiceFreqHz() : 0;
    const micRms = mic.isRunning() ? mic.getRms() : 0;
    const drive = computeParticleDrive(telemetry, voiceHzMic, tunables.micOn, micRms);

    latRing.push(telemetry.latencyMs);
    if (latRing.length > 24) latRing.shift();
    const latencyMsAvg = latRing.reduce((a, b) => a + b, 0) / latRing.length;

    const orbit = now * 0.00005;
    const r = 74 + Math.sin(now * 0.0003) * 2;
    particles.camera.position.set(Math.cos(orbit) * r, Math.sin(orbit * 0.6) * 5, Math.sin(orbit) * r * 0.85 + 6);
    particles.camera.lookAt(0, 0, 0);

    particles.update(drive, now / 1000);
    particles.render();

    hud.update({
      fps,
      latencyMsAvg,
      particleCount: particles.getInstanceCount(),
      coherence: drive.coherence,
    });

  }

  loop();
}

main();
