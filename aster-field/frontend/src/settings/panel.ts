/** 设置层 — 日记阅读 6 位密码 */
const TOKEN_KEY = 'field-diary-token';

export function getDiaryToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setDiaryToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearDiaryToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export function mountSettings(): { openSettings: () => void } {
  const overlay = document.createElement('div');
  overlay.id = 'settings-overlay';
  overlay.style.cssText = `position:fixed;inset:0;z-index:25;display:none;
    background:rgba(10,9,16,.94);backdrop-filter:blur(14px);
    overflow-y:auto;padding:8vh 6vw;font-family:var(--body,'Instrument Sans',sans-serif);`;
  overlay.innerHTML = `
    <div style="max-width:420px;margin:0 auto;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:28px;">
        <h2 style="font-family:'Fraunces',serif;font-weight:400;font-size:22px;color:var(--dew,#EDEAF4);">设置</h2>
        <span id="settings-close" style="font-family:var(--mono,monospace);font-size:12px;
          color:var(--vine,#8B8698);cursor:pointer;">ESC 关闭</span>
      </div>
      <p style="font-size:13px;color:var(--vine,#8B8698);line-height:1.6;margin-bottom:20px;">
        日记阅读密码（6 位数字）。双击心脏打开日记前需输入。22:30 自动写入不需要密码。
      </p>
      <div id="settings-status" style="font-family:var(--mono,monospace);font-size:11px;
        color:var(--vine,#8B8698);margin-bottom:16px;"></div>
      <label style="display:block;font-family:var(--mono,monospace);font-size:11px;color:var(--vine);margin-bottom:6px;"
        id="lbl-old">原密码</label>
      <input id="pin-old" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="6"
        autocomplete="off" style="width:100%;margin-bottom:14px;padding:12px 14px;border-radius:8px;
        border:1px solid rgba(167,139,224,.25);background:rgba(20,18,32,.55);color:var(--dew);font-size:18px;
        letter-spacing:.35em;text-align:center;font-family:var(--mono,monospace);">
      <label style="display:block;font-family:var(--mono,monospace);font-size:11px;color:var(--vine);margin-bottom:6px;">
        新密码（6 位）</label>
      <input id="pin-new" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="6"
        autocomplete="off" style="width:100%;margin-bottom:14px;padding:12px 14px;border-radius:8px;
        border:1px solid rgba(167,139,224,.25);background:rgba(20,18,32,.55);color:var(--dew);font-size:18px;
        letter-spacing:.35em;text-align:center;font-family:var(--mono,monospace);">
      <label style="display:block;font-family:var(--mono,monospace);font-size:11px;color:var(--vine);margin-bottom:6px;">
        确认新密码</label>
      <input id="pin-confirm" type="password" inputmode="numeric" pattern="[0-9]*" maxlength="6"
        autocomplete="off" style="width:100%;margin-bottom:18px;padding:12px 14px;border-radius:8px;
        border:1px solid rgba(167,139,224,.25);background:rgba(20,18,32,.55);color:var(--dew);font-size:18px;
        letter-spacing:.35em;text-align:center;font-family:var(--mono,monospace);">
      <button id="pin-save" type="button" style="width:100%;padding:12px;border:none;border-radius:8px;
        background:rgba(167,139,224,.35);color:var(--dew);font-family:var(--mono,monospace);font-size:12px;
        letter-spacing:.12em;cursor:pointer;">保存密码</button>
      <p id="settings-msg" style="margin-top:14px;font-family:var(--mono,monospace);font-size:11px;min-height:1.4em;"></p>
    </div>`;
  document.body.appendChild(overlay);

  const close = () => { overlay.style.display = 'none'; };
  const openSettings = () => { void refresh(); overlay.style.display = 'block'; };
  overlay.querySelector('#settings-close')!.addEventListener('click', close);
  addEventListener('keydown', e => { if (e.key === 'Escape' && overlay.style.display === 'block') close(); });

  const msg = overlay.querySelector('#settings-msg') as HTMLElement;
  const status = overlay.querySelector('#settings-status') as HTMLElement;
  const oldRow = overlay.querySelector('#lbl-old') as HTMLElement;
  const oldIn = overlay.querySelector('#pin-old') as HTMLInputElement;

  async function refresh(): Promise<void> {
    try {
      const r = await fetch('/diary/settings');
      const d = await r.json();
      const set = !!d.pin_set;
      status.textContent = set ? '已设置阅读密码' : '尚未设置 — 双击心脏可直接阅读';
      oldRow.style.display = set ? 'block' : 'none';
      oldIn.style.display = set ? 'block' : 'none';
      oldIn.value = '';
    } catch {
      status.textContent = '无法连接 FIELD';
    }
  }

  overlay.querySelector('#pin-save')!.addEventListener('click', async () => {
    const neu = (overlay.querySelector('#pin-new') as HTMLInputElement).value;
    const conf = (overlay.querySelector('#pin-confirm') as HTMLInputElement).value;
    const old = oldIn.value;
    msg.style.color = 'var(--vine)';
    if (!/^\d{6}$/.test(neu)) { msg.textContent = '新密码须为 6 位数字'; return; }
    if (neu !== conf) { msg.textContent = '两次输入不一致'; return; }
    const body: Record<string, string> = { pin: neu };
    if (old) body.old_pin = old;
    const r = await fetch('/diary/pin', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const d = await r.json();
    if (!d.ok) { msg.textContent = d.error || '保存失败'; msg.style.color = 'var(--warn)'; return; }
    clearDiaryToken();
    msg.textContent = '已保存 — 下次打开日记需输入新密码';
    msg.style.color = 'var(--seal)';
    (overlay.querySelector('#pin-new') as HTMLInputElement).value = '';
    (overlay.querySelector('#pin-confirm') as HTMLInputElement).value = '';
    await refresh();
  });
  return { openSettings };
}
