import { Field } from './field/field';
import { connectState } from './net/sse';
import { mountDiary } from './diary/panel';
import { mountSettings } from './settings/panel';
import { mountChatPanel } from './ui/chat_panel';
import { applyStateGlow } from './ui/state_glow';
import type { FieldState } from './state/machine';

const $ = (id: string) => document.getElementById(id) as HTMLElement;
const field = new Field(document.getElementById('field') as HTMLCanvasElement);
const { openDiary } = mountDiary(document.getElementById('field')!);
const { openSettings } = mountSettings();
$('btn-diary').addEventListener('click', e => { e.preventDefault(); openDiary(); });
$('btn-settings').addEventListener('click', e => { e.preventDefault(); openSettings(); });
field.onFps = (f) => ($('hFps').textContent = String(f));
field.start();

const wordEl = $('stateWord');
const cssVar = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function applyState(s: FieldState): void {
  field.setState(s);
  wordEl.textContent = s; $('hState').textContent = s;
  const color = s === 'output' ? cssVar('--gold') : s === 'thinking' ? cssVar('--perilla')
    : s === 'error' ? cssVar('--warn') : cssVar('--vine');
  applyStateGlow(wordEl, s, color || '#8B8698');
}
let cohOverride: number | null = null;
function setCoh(v: number): void { field.setCoherence(v); $('hCoh').textContent = v.toFixed(2); }
($('coh') as HTMLInputElement).addEventListener('input', (e) => {
  cohOverride = Number((e.target as HTMLInputElement).value) / 100; setCoh(cohOverride);
});
const setLink = (id: string, ok?: boolean) => {
  const el = $(id); el.textContent = ok ? 'ok' : '—'; el.className = ok ? 'on' : 'off';
};

connectState((d) => {
  applyState(d.state);
  if (d.state === 'output') field.ripple();
  $('hTok').textContent = String(d.tokens ?? 0);
  if (cohOverride === null && typeof d.coherence === 'number') setCoh(d.coherence);
  setLink('lGw', d.links?.gateway); setLink('lGd', d.links?.garden);
}, (up) => { setLink('lBridge', up); $('hMode').textContent = up ? 'LIVE' : 'OFFLINE'; });

mountChatPanel(applyState);
const askEl = $('ask') as HTMLInputElement;
askEl.addEventListener('focus', () => field.setPresenceBoost(true));
askEl.addEventListener('blur', () => field.setPresenceBoost(false));
applyState('idle');
