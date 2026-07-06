const cache = new Map<string, string>();

/** Pre-render state word glow once per (word,color) — not per RAF frame. */
export function applyStateGlow(el: HTMLElement, word: string, color: string): void {
  const key = `${word}::${color}`;
  if (el.dataset.glowKey === key) return;
  el.dataset.glowKey = key;
  let url = cache.get(key);
  if (!url) {
    const c = document.createElement('canvas');
    c.width = 220; c.height = 40;
    const ctx = c.getContext('2d')!;
    ctx.clearRect(0, 0, c.width, c.height);
    ctx.font = '500 12px "IBM Plex Mono", monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = color;
    ctx.shadowColor = color;
    ctx.shadowBlur = 14;
    ctx.fillText(word.toUpperCase(), c.width / 2, c.height / 2);
    url = c.toDataURL('image/png');
    cache.set(key, url);
  }
  el.style.backgroundImage = `url(${url})`;
  el.style.backgroundRepeat = 'no-repeat';
  el.style.backgroundPosition = 'center';
  el.style.backgroundSize = 'contain';
  el.style.color = 'transparent';
  el.style.letterSpacing = '0.55em';
}
