/** 日记层 — 全在 JS 动态创建,不依赖 index.html / style.css 改动 */
import { clearDiaryToken, getDiaryToken, setDiaryToken } from '../settings/panel';
import { diaryAuthFetch, type DiaryAuthFetch } from '../gateway/diaryAuthFetch';

interface Reply { id: number; author: string; text: string; ts: string; }
interface Entry { id: number; ts: string; text: string; replies?: Reply[]; }

const esc = (s: string) => s.replace(/[<>&]/g, c => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]!));

function ensureDiaryStyles(): void {
  if (document.getElementById('diary-ui-style')) return;
  const s = document.createElement('style');
  s.id = 'diary-ui-style';
  s.textContent = `
body.diary-open canvas#field{z-index:1;pointer-events:none}
#diary-overlay{position:fixed;inset:0;z-index:99990;display:none;flex-direction:column;
  background:rgba(10,9,16,.96);font-family:var(--body,'Instrument Sans',sans-serif);overflow:hidden}
.diary-scroll{flex:1;min-height:0;overflow-y:auto;padding:8vh 6vw 200px}
.diary-inner{max-width:640px;margin:0 auto}
.diary-header{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:32px}
.diary-title{font-family:'Fraunces',serif;font-weight:400;font-size:26px;color:var(--dew,#EDEAF4)}
.diary-close{font-family:var(--mono,monospace);font-size:12px;color:var(--vine,#8B8698);cursor:pointer}
.diary-integrity{font-family:var(--mono,monospace);font-size:10.5px;color:var(--vine,#8B8698);margin-bottom:24px}
.diary-entry{margin-bottom:28px;padding-bottom:24px;border-bottom:1px solid rgba(167,139,224,.12)}
.diary-entry-ts{font-family:monospace;font-size:10px;color:#5A5568;margin-bottom:8px;display:block}
.diary-entry-text{color:#EDEAF4;font-size:15px;line-height:1.75;white-space:pre-wrap}
.diary-past-reply{margin:12px 0 0;padding:10px 12px;border-left:3px solid rgba(232,201,138,.5);
  background:rgba(232,201,138,.08);border-radius:0 8px 8px 0}
.diary-past-reply-label{font-family:monospace;font-size:10px;color:#E8C98A;margin-bottom:6px}
.diary-past-reply-text{color:#EDEAF4;font-size:14px;line-height:1.7;white-space:pre-wrap}
.diary-muted{color:#8B8698;font-family:monospace}
.diary-err{color:#C97B6E}
#diary-reply-bar{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;display:none;
  padding:20px 24px max(22px,env(safe-area-inset-bottom));border-top:4px solid #E8C98A;
  background:rgba(10,9,16,.98);box-shadow:0 -20px 60px rgba(0,0,0,.95)}
.diary-reply-title{font-family:monospace;font-size:14px;color:#E8C98A;letter-spacing:.12em;margin-bottom:10px}
.diary-reply-row{display:flex;gap:12px;align-items:flex-end;max-width:680px;margin:0 auto}
.diary-unlock-row{display:none;gap:12px;align-items:center;max-width:680px;margin:0 auto}
#diary-reply-bar.diary-locked .diary-reply-row{display:none}
#diary-reply-bar.diary-locked .diary-unlock-row{display:flex}
.diary-pin-input{flex:1;padding:14px 16px;border-radius:10px;border:2px solid #E8C98A;
  background:#141220;color:#EDEAF4;font-size:22px;letter-spacing:.4em;text-align:center;font-family:monospace}
.diary-pin-btn{flex-shrink:0;padding:14px 24px;border-radius:10px;border:2px solid #E8C98A;
  background:#E8C98A;color:#0A0910;font-family:monospace;font-size:14px;font-weight:700;cursor:pointer}
.diary-pin-err{font-family:monospace;font-size:11px;color:#C97B6E;margin-top:8px;min-height:1.2em;text-align:center}
.diary-pin-wrap{max-width:320px;margin:10vh auto 0;text-align:center}
.diary-pin-label{font-family:monospace;font-size:11px;color:#8B8698;margin-bottom:16px}
#diary-reply-in{flex:1;min-height:72px;padding:14px 16px;border-radius:10px;border:2px solid #E8C98A;
  background:#141220;color:#EDEAF4;font-size:16px;line-height:1.65;resize:vertical;font-family:inherit}
#diary-reply-in:disabled{opacity:.65}
#diary-reply-send{flex-shrink:0;padding:14px 24px;border-radius:10px;border:2px solid #E8C98A;
  background:#E8C98A;color:#0A0910;font-family:monospace;font-size:14px;font-weight:700;cursor:pointer}
#diary-reply-send:disabled{opacity:.55;cursor:not-allowed}
.diary-reply-msg{font-family:monospace;font-size:11px;color:#8B8698;margin-top:8px;min-height:1.2em;text-align:center}
body.diary-open #diary-overlay{display:flex!important}
body.diary-open #diary-reply-bar{display:block!important}
body.diary-open .dock,body.diary-open #raw-panel,body.diary-open #reply,
body.diary-open #chat-meta,body.diary-open #chat-artifact{display:none!important}`;
  document.head.appendChild(s);
}

function pinPad(onOk: (pin: string) => void): HTMLElement {
  const el = document.createElement('div');
  el.className = 'diary-pin-wrap';
  el.innerHTML = `
    <p class="diary-pin-label">输入 6 位阅读密码</p>
    <input class="diary-pin-input" type="password" inputmode="numeric" maxlength="6" autocomplete="off">
    <button type="button" class="diary-pin-btn">解锁</button>
    <p class="diary-pin-err"></p>`;
  const input = el.querySelector('.diary-pin-input') as HTMLInputElement;
  const err = el.querySelector('.diary-pin-err') as HTMLElement;
  const submit = () => {
    const pin = input.value;
    if (!/^\d{6}$/.test(pin)) { err.textContent = '需要 6 位数字'; return; }
    onOk(pin);
  };
  requestAnimationFrame(() => input.focus());
  input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
  el.querySelector('.diary-pin-btn')!.addEventListener('click', submit);
  return el;
}

export function mountDiary(canvas: HTMLElement, apiFetch: DiaryAuthFetch = diaryAuthFetch): { openDiary: () => void } {
  ensureDiaryStyles();
  document.getElementById('diary-overlay')?.remove();
  document.getElementById('diary-reply-bar')?.remove();

  const overlay = document.createElement('div');
  overlay.id = 'diary-overlay';
  overlay.innerHTML = `
    <div class="diary-scroll">
      <div class="diary-inner">
        <div class="diary-header">
          <h2 class="diary-title">日记</h2>
          <span class="diary-close">ESC 关闭</span>
        </div>
        <div class="diary-integrity"></div>
        <div class="diary-entries"></div>
      </div>
    </div>`;

  const replyBar = document.createElement('div');
  replyBar.id = 'diary-reply-bar';
  replyBar.innerHTML = `
    <div class="diary-inner">
      <div class="diary-reply-title" id="diary-bar-title">写给它的回信</div>
      <div class="diary-unlock-row" hidden>
        <input id="diary-pin-in" class="diary-pin-input" type="password" inputmode="numeric"
          maxlength="6" autocomplete="off" placeholder="••••••">
        <button type="button" id="diary-pin-btn" class="diary-pin-btn">解锁</button>
      </div>
      <p class="diary-pin-err" id="diary-pin-err" hidden></p>
      <div class="diary-reply-row">
        <textarea id="diary-reply-in" rows="2" placeholder="先输入上方 6 位密码解锁…" disabled></textarea>
        <button type="button" id="diary-reply-send" disabled>送信</button>
      </div>
      <p class="diary-reply-msg"></p>
    </div>`;

  document.body.appendChild(overlay);
  document.body.appendChild(replyBar);

  const entriesEl = overlay.querySelector('.diary-entries') as HTMLElement;
  const integrityEl = overlay.querySelector('.diary-integrity') as HTMLElement;
  const barTitle = replyBar.querySelector('#diary-bar-title') as HTMLElement;
  const pinIn = replyBar.querySelector('#diary-pin-in') as HTMLInputElement;
  const pinBtn = replyBar.querySelector('#diary-pin-btn') as HTMLButtonElement;
  const pinErr = replyBar.querySelector('#diary-pin-err') as HTMLElement;
  const rin = replyBar.querySelector('#diary-reply-in') as HTMLTextAreaElement;
  const rsend = replyBar.querySelector('#diary-reply-send') as HTMLButtonElement;
  const rmsg = replyBar.querySelector('.diary-reply-msg') as HTMLElement;

  let authToken = getDiaryToken() || '';
  let latestEntryId: number | null = null;
  let unlocked = false;

  const authHeaders = (): Record<string, string> =>
    authToken ? { Authorization: `Bearer ${authToken}` } : {};

  const diaryFetch = (input: string, init: RequestInit = {}): Promise<Response> =>
    apiFetch(input, { cache: 'no-store', ...init, headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) } });

  const setLocked = (locked: boolean, hint = ''): void => {
    replyBar.classList.remove('diary-locked');
    replyBar.style.display = 'block';
    pinErr.hidden = true;
    pinErr.textContent = '';
    rmsg.textContent = '';
    barTitle.textContent = '写给它的回信';
    rin.disabled = locked;
    rsend.disabled = locked;
    rin.placeholder = locked ? (hint || '先输入上方 6 位密码解锁…') : (hint || '写给它的回信…');
  };

  const close = (): void => {
    overlay.style.display = 'none';
    replyBar.style.display = 'none';
    document.body.classList.remove('diary-open');
    clearDiaryToken();
    authToken = '';
    unlocked = false;
  };
  overlay.querySelector('.diary-close')!.addEventListener('click', close);
  addEventListener('keydown', e => { if (e.key === 'Escape' && overlay.style.display !== 'none') close(); });

  const replyLine = (r: Reply): string => {
    const mine = r.author === 'lyra';
    const who = mine ? 'Lyra' : (r.author === 'aster' ? 'Aster' : 'Grid');
    return `<div class="diary-past-reply">
      <div class="diary-past-reply-label">${who} · ${esc(r.ts)}</div>
      <div class="diary-past-reply-text">${esc(r.text)}</div>
    </div>`;
  };

  const entryBlock = (e: Entry): string => `
    <article class="diary-entry" data-entry="${e.id}">
      <time class="diary-entry-ts">${esc(e.ts)}</time>
      <div class="diary-entry-text">${esc(e.text)}</div>
      ${(e.replies || []).map(replyLine).join('')}
    </article>`;

  async function sendReply(): Promise<void> {
    const text = rin.value.trim();
    if (!unlocked || !latestEntryId || !text) return;
    rsend.disabled = true;
    rmsg.textContent = '发送中…';
    try {
      const res = await diaryFetch('/diary/reply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry_id: latestEntryId, text }),
      });
      if (res.status === 401) {
        clearDiaryToken();
        authToken = '';
        await promptUnlock();
        return;
      }
      if (!res.ok) throw new Error(String(res.status));
      const body = await res.json() as { grid_sync?: { ok?: boolean; error?: string | null } };
      rin.value = '';
      if (body.grid_sync?.ok) {
        rmsg.textContent = '已送出 · Grid 已收到';
      } else if (body.grid_sync?.error) {
        rmsg.textContent = `已存本地 · Grid 未同步：${body.grid_sync.error}`;
      } else {
        rmsg.textContent = '已送出';
      }
      await load();
    } catch {
      rmsg.textContent = '发送失败，请重试';
      rsend.disabled = false;
    }
  }

  rsend.addEventListener('click', () => { void sendReply(); });
  rin.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void sendReply(); }
  });

  const submitPin = (): void => {
    const pin = pinIn.value;
    if (!/^\d{6}$/.test(pin)) { pinErr.textContent = '需要 6 位数字'; pinErr.hidden = false; return; }
    void tryUnlock(pin);
  };
  pinBtn.addEventListener('click', submitPin);
  pinIn.addEventListener('keydown', e => { if (e.key === 'Enter') submitPin(); });

  async function tryUnlock(pin: string, errEl?: HTMLElement): Promise<void> {
    const err = errEl || pinErr;
    err.textContent = '';
    if (!errEl) pinBtn.disabled = true;
    try {
      const r = await apiFetch('/diary/unlock', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }),
      });
      const d = await r.json();
      if (!d.ok) {
        err.textContent = d.error || '密码不对';
        if (!errEl) pinErr.hidden = false;
        return;
      }
      authToken = d.token;
      setDiaryToken(d.token);
      pinIn.value = '';
      await load();
    } catch {
      err.textContent = '解锁失败，请重试';
      if (!errEl) pinErr.hidden = false;
    } finally {
      if (!errEl) pinBtn.disabled = false;
    }
  }

  async function promptUnlock(): Promise<void> {
    unlocked = false;
    latestEntryId = null;
    setLocked(true);
    integrityEl.textContent = '输入密码后显示日记与回复';
    entriesEl.innerHTML = '';
    const pad = pinPad(pin => { void tryUnlock(pin, pad.querySelector('.diary-pin-err') as HTMLElement); });
    entriesEl.append(pad);
  }

  async function load(): Promise<void> {
    entriesEl.innerHTML = '<span class="diary-muted">…</span>';
    try {
      const r = await diaryFetch('/diary');
      if (r.status === 401) {
        clearDiaryToken();
        authToken = '';
        await promptUnlock();
        return;
      }
      const d = await r.json();
      unlocked = true;
      integrityEl.textContent = d.integrity?.ok
        ? `完好 · ${d.integrity.count} 篇 · 只给 Lyra 看`
        : `⚠ 链在第 ${d.integrity?.broken_at} 篇断开`;
      const entries = d.entries as Entry[];
      if (!entries.length) {
        latestEntryId = null;
        entriesEl.innerHTML = '<span class="diary-muted">还没有一篇。</span>';
        setLocked(true, '暂无日记可回复');
        return;
      }
      latestEntryId = (d.reply_target_entry_id as number | null) ?? null;
      if (!latestEntryId && entries.length) {
        latestEntryId = entries[entries.length - 1].id;
      }
      const target = entries.find(e => e.id === latestEntryId);
      const latestTs = target?.ts.slice(0, 10) ?? '';
      entriesEl.innerHTML = entries.map(entryBlock).join('');
      setLocked(false, `回复最新一篇（${latestTs}）…`);
    } catch {
      entriesEl.innerHTML = '<span class="diary-err">读取失败</span>';
      setLocked(true);
    }
  }

  async function open(): Promise<void> {
    overlay.style.display = 'flex';
    replyBar.style.display = 'block';
    document.body.classList.add('diary-open');
    authToken = getDiaryToken() || '';
    setLocked(true);
    try {
      const cfg = await (await apiFetch('/diary/settings')).json();
      if (cfg.pin_set) {
        clearDiaryToken();
        authToken = '';
        await promptUnlock();
        return;
      }
    } catch {
      entriesEl.innerHTML = '<span class="diary-err">无法连接 FIELD</span>';
      setLocked(true);
      return;
    }
    await load();
  }

  canvas.addEventListener('dblclick', () => { void open(); });
  return { openDiary: () => { void open(); } };
}
