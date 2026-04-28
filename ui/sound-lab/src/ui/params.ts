import GUI from 'lil-gui';

export type Tunables = {
  particleCount: number;
  dispersion: number;
  micOn: boolean;
};

export type ParamsCallbacks = {
  onParticleCount: (n: number) => void;
  onDispersion: (d: number) => void;
  onMicToggle: (on: boolean) => void;
};

/**
 * lil-gui sliders wired to tunables (right panel).
 * Mutates `state` in place so UI stays in sync with app.
 */
export function createParamsPanel(
  mount: HTMLElement,
  state: Tunables,
  cb: ParamsCallbacks,
): { gui: GUI; setMicGui: (on: boolean) => void } {
  const gui = new GUI({ container: mount, title: 'Garden' });
  gui
    .add(state, 'particleCount', 20_000, 200_000, 1000)
    .name('particleCount')
    .onChange((v: number) => cb.onParticleCount(Math.floor(v)));
  gui
    .add(state, 'dispersion', 0.4, 3.0, 0.02)
    .name('dispersion')
    .onChange((v: number) => cb.onDispersion(v));
  const micCtrl = gui.add(state, 'micOn').name('mic').onChange((v: boolean) => cb.onMicToggle(v));
  return {
    gui,
    setMicGui(on: boolean) {
      state.micOn = on;
      micCtrl.updateDisplay();
    },
  };
}
