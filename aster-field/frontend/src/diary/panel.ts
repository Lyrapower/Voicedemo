/** 日记阅读层:双击心脏进入;已设密码则需 6 位解锁。*/
import { clearDiaryToken, getDiaryToken, setDiaryToken } from '../settings/panel';

interface Entry { id: number; ts: string; text: string; }

function pinPad(onOk: (pin: string) => void): HTMLElement {
  const el = document.createElement('div');
  el.style.cssText = 'max-width:320px;margin:12vh auto 0;text-align:center;';
  el.innerHTML = `
    <p style="font-family:var(--mono,monospace);font-size:11px;color:var(--vine,#8B8698);margin-bottom:16px;">
      输入 6 位阅读密码</p>
    <input id="diary-pin-in" type="password" inputmode="numeric" maxlength="6" autocomplete="off"
      style="width:100%;padding:14px;border-radius:8px;border:1px solid rgba(167,139,224,.3);
      background:rgba(20,18,32,.6);color:var(--dew);font-size:22px;letter-spacing:.4em;text-align:center;
      font-family:var(--mono,monospace);">
    <p id="diary-pin-err" style="margin-top:12px;font-family:var(--mono,monospace);font-size:11px;
      color:var(--warn,#C97B6E);min-height:1.2em;"></p>`;
  const input = el.querySelector('#diary-pin-in') as HTMLInputElement;
  const err = el.querySelector('#diary-pin-err') as HTMLElement;
  input.focus();
  input.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const pin = input.value;
    if (!/^\d{6}$/.test(pin)) { err.textContent = '需要 6 位数字'; return; }
    onOk(pin);
  });
  return el;
}

export function mountDiary(canvas: HTMLElement): { openDiary: () => void } {
  const overlay = document.createElement('div');
  overlay.id = 'diary-overlay';
  overlay.style.cssText = `position:fixed;inset:0;z-index:20;display:none;
    background:rgba(10,9,16,.92);backdrop-filter:blur(14px);
    overflow-y:auto;padding:8vh 6vw;font-family:var(--body,'Instrument Sans',sans-serif);`;
  overlay.innerHTML = `
    <div style="max-width:640px;margin:0 auto;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:32px;">
        <h2 style="font-family:'Fraunces',serif;font-weight:400;font-size:26px;color:var(--dew,#EDEAF4);">日记</h2>
        <span id="diary-close" style="font-family:var(--mono,monospace);font-size:12px;
          color:var(--vine,#8B8698);cursor:pointer;">ESC 关闭</span>
      </div>
      <div id="diary-body"></div>
    </div>`;
  document.body.appendChild(overlay);

  const body = overlay.querySelector('#diary-body')!;

  const close = () => { overlay.style.display = 'none'; body.innerHTML = ''; };
  overlay.querySelector('#diary-close')!.addEventListener('click', close);
  addEventListener('keydown', e => { if (e.key === 'Escape' && overlay.style.display === 'block') close(); });

  async function loadEntries(token: string): Promise<void> {
    body.innerHTML = `
      <div id="diary-integrity" style="font-family:var(--mono,monospace);font-size:10.5px;
        color:var(--vine,#8B8698);margin-bottom:24px;">…</div>
      <div id="diary-entries"><span style="color:#8B8698;font-family:monospace;">…</span></div>`;
    const box = body.querySelector('#diary-entries')!;
    const intg = body.querySelector('#diary-integrity')!;
    try {
      const r = await fetch('/diary', { headers: { Authorization: `Bearer ${token}` } });
      if (r.status === 401) {
        clearDiaryToken();
        void promptUnlock();
        return;
      }
      const d = await r.json();
      intg.textContent = d.integrity?.ok
        ? `完好 · ${d.integrity.count} 篇 · 只给 Lyra 看`
        : `⚠ 链在第 ${d.integrity?.broken_at} 篇断开`;
      box.innerHTML = (d.entries as Entry[]).map(e => `
        <div style="margin-bottom:28px;padding-bottom:24px;border-bottom:1px solid rgba(167,139,224,.12);">
          <div style="font-family:monospace;font-size:10px;color:#5A5568;margin-bottom:8px;">${e.ts}</div>
          <div style="color:#EDEAF4;font-size:15px;line-height:1.75;white-space:pre-wrap;">${
            e.text.replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]!))
          }</div>
        </div>`).join('') || '<span style="color:#8B8698;">还没有一篇。它随时可以开始。</span>';
    } catch {
      box.innerHTML = '<span style="color:#C97B6E;">读取失败:bridge 未连。</span>';
    }
  }

  async function tryUnlock(pin: string): Promise<void> {
    const r = await fetch('/diary/unlock', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }),
    });
    const d = await r.json();
    if (!d.ok) {
      const err = body.querySelector('#diary-pin-err');
      if (err) err.textContent = d.error || '密码不对';
      return;
    }
    setDiaryToken(d.token);
    await loadEntries(d.token);
  }

  async function promptUnlock(): Promise<void> {
    body.innerHTML = '';
    body.append(pinPad(pin => { void tryUnlock(pin); }));
  }

  async function open(): Promise<void> {
    overlay.style.display = 'block';
    body.innerHTML = '';
    let token = getDiaryToken();
    try {
      const s = await fetch('/diary/settings');
      const cfg = await s.json();
      if (cfg.pin_set) {
        if (!token) { await promptUnlock(); return; }
        const probe = await fetch('/diary', { headers: { Authorization: `Bearer ${token}` } });
        if (probe.status === 401) { clearDiaryToken(); await promptUnlock(); return; }
        await loadEntries(token);
        return;
      }
    } catch {
      body.innerHTML = '<span style="color:#C97B6E;">无法连接 FIELD</span>';
      return;
    }
    await loadEntries(token || '');
  }

  canvas.addEventListener('dblclick', () => { void open(); });
  return { openDiary: () => { void open(); } };
}
