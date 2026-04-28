import './style.css';
import { AudioAnalyser } from './audio/analyser';
import { computeParticleDrive, type TelemetrySample } from './core/controller';
import { ParticleRenderer } from './core/renderer';
import { createHud } from './ui/hud';
import { createParamsPanel, type Tunables } from './ui/params';
import { setupGui, type VisualControls } from './gui';

const TELEMETRY_URL = '/api/telemetry';

/** Set false when fetch to proxy/backend fails (HUD shows "telemetry mock"). */
let telemetryLive = false;

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
    telemetryLive = true;
    telemetry = {
      t: typeof j.t === 'number' ? j.t : performance.now() / 1000,
      voiceFreq: typeof j.voiceFreq === 'number' ? j.voiceFreq : telemetry.voiceFreq,
      aiFreq: typeof j.aiFreq === 'number' ? j.aiFreq : telemetry.aiFreq,
      aiAmplitude: typeof j.aiAmplitude === 'number' ? j.aiAmplitude : telemetry.aiAmplitude,
      latencyMs: typeof j.latencyMs === 'number' ? j.latencyMs : dt,
    };
  } catch {
    telemetryLive = false;
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
  const visual: VisualControls = {
    pointSize: 1.5,
    hueShift: 0,
  };

  const analyser = new AudioAnalyser();
  const particles = new ParticleRenderer(canvas, {
    particleCount: tunables.particleCount,
    dispersion: tunables.dispersion,
  });
  particles.setPointSize(visual.pointSize);
  particles.setHueShift(visual.hueShift);

  const demo = new Audio('/assets/demo.mp3');
  demo.loop = true;
  demo.volume = 0.35;
  let micAllowed = false;
  const startDemoAudio = async (): Promise<void> => {
    try {
      await analyser.useMediaElement(demo);
      await demo.play();
    } catch {
      /* autoplay may be blocked until user gesture */
    }
  };

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
            await analyser.useMicrophone();
            micAllowed = true;
            if (!demo.paused) demo.pause();
          } catch {
            tunables.micOn = false;
            setMicGui(false);
            await startDemoAudio();
          }
        } else {
          analyser.stop();
          micAllowed = false;
          await startDemoAudio();
        }
      })();
    },
  });
  setupGui(guiMount, visual, (state) => {
    particles.setPointSize(state.pointSize);
    particles.setHueShift(state.hueShift);
  });

  // Auto-play demo track in dev when mic permission is denied/unavailable.
  if (location.hostname === '127.0.0.1' || location.hostname === 'localhost') {
    if ('permissions' in navigator && navigator.permissions) {
      void navigator.permissions
        .query({ name: 'microphone' as PermissionName })
        .then(async (p) => {
          if (p.state === 'denied') await startDemoAudio();
        })
        .catch(() => {
          /* permission API unsupported */
        });
    } else {
      void startDemoAudio();
    }
  }

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

    const spectrum = analyser.getSpectrum();
    const drive = computeParticleDrive(
      telemetry,
      spectrum.freq,
      micAllowed && tunables.micOn,
      spectrum.amp,
      spectrum.freq,
    );

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
      telemetry: telemetryLive ? 'live' : 'mock',
    });

  }

  loop();
}

main();
