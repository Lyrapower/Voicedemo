import GUI from 'lil-gui';

export type VisualControls = {
  pointSize: number;
  hueShift: number;
};

export function setupGui(
  mount: HTMLElement,
  state: VisualControls,
  onChange: (s: VisualControls) => void,
): GUI {
  const gui = new GUI({ container: mount, title: 'Visuals' });
  gui.add(state, 'pointSize', 0.5, 6, 0.1).name('pointSize').onChange(() => onChange(state));
  gui.add(state, 'hueShift', 0, 360, 1).name('hueShift').onChange(() => onChange(state));
  return gui;
}

