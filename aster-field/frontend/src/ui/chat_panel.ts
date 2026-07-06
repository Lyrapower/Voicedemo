import type { FieldState } from '../state/machine';
import { sendChat, type ChatDone, type TaskType } from '../net/chat';

const JSON_TASKS = new Set<TaskType>(['compile_json', 'handoff_protocol']);
const MAX_AUTO_CONTINUE = 3;

function detectTask(message: string): TaskType {
  const low = message.toLowerCase();
  if (message.includes('这是你的日记本')) return 'diary';
  if (low.includes('handoff_protocol') || low.includes('handoff protocol') || message.includes('交接协议'))
    return 'handoff_protocol';
  if (low.includes('compile_json') || (low.includes('json') && /compile|schema|artifact|protocol|handoff/.test(low)))
    return 'compile_json';
  return 'chat';
}

function isJsonTask(t?: TaskType): boolean {
  return !!t && JSON_TASKS.has(t);
}

function heartbeatClass(d: ChatDone): string {
  if (d.contract_flag) return 'contract';
  if (d.finish_reason === 'length' || d.truncated) return 'length';
  if (d.finish_reason === 'stop') return 'stop';
  return 'idle';
}

export function mountChatPanel(applyState: (s: FieldState) => void): void {
  const replyEl = document.getElementById('reply')!;
  const metaEl = document.getElementById('chat-meta')!;
  const artifactEl = document.getElementById('chat-artifact')!;
  const rawEl = document.getElementById('raw-out')!;
  const rawPanel = document.getElementById('raw-panel')!;
  const continueBtn = document.getElementById('chat-continue') as HTMLButtonElement;
  const ask = document.getElementById('ask') as HTMLInputElement;

  let rawText = '';
  let session: { message: string; task: TaskType; merged: string; part: number } | null = null;

  const setRaw = (t: string) => { rawText = t; rawEl.textContent = t; };

  const renderMeta = (d: ChatDone) => {
    const parts = [
      `task ${d.task_type ?? 'chat'}`,
      `max_tokens ${d.max_tokens ?? '—'}`,
      `served_by ${d.served_by ?? '—'}`,
      `finish ${d.finish_reason ?? '—'}`,
    ];
    if (d.truncated) parts.push('truncated (transport)');
    if ((d.continuation_part ?? 0) > 0) parts.push(`part ${(d.continuation_part ?? 0) + 1}`);
    if (d.merged_json_valid) parts.push('merged_json_valid=true');
    if (d.status) parts.push(`status=${d.status}`);
    if (d.contract_flag) parts.push(`contract_flag=${d.contract_flag}`);
    metaEl.innerHTML = `<span class="gw-dot ${heartbeatClass(d)}" title="gateway heartbeat"></span>${parts.join(' · ')}`;
    metaEl.className = 'chat-meta' + (d.status === 'INCOMPLETE_ARTIFACT' ? ' warn' : d.status === 'PASS' ? ' ok' : '');
  };

  const renderArtifact = (d: ChatDone) => {
    artifactEl.innerHTML = '';
    if (!isJsonTask(d.task_type)) return;
    if (d.artifact?.ok && d.artifact.json !== undefined && typeof d.artifact.json === 'object' && d.artifact.json) {
      const wrap = document.createElement('div');
      wrap.className = 'artifact-json';
      Object.entries(d.artifact.json as Record<string, unknown>).forEach(([k, v], i) => {
        const row = document.createElement('div');
        row.className = 'artifact-row';
        row.style.animationDelay = `${i * 80}ms`;
        const key = document.createElement('span');
        key.className = 'artifact-key';
        key.textContent = k;
        const val = document.createElement('pre');
        val.textContent = typeof v === 'string' ? v : JSON.stringify(v, null, 2);
        row.append(key, val);
        wrap.append(row);
      });
      artifactEl.append(wrap);
      return;
    }
    const span = document.createElement('span');
    span.className = 'artifact-incomplete';
    span.textContent = `status=INCOMPLETE_ARTIFACT${d.artifact?.error ? ` · ${d.artifact.error}` : ''}`;
    artifactEl.append(span);
  };

  const runOnce = (message: string, task: TaskType, merged: string, part: number): Promise<ChatDone | null> => {
    let partText = '';
    return new Promise(resolve => {
      replyEl.textContent = '';
      void sendChat(
        {
          message: part > 0 ? '' : message,
          task_type: task,
          continue: part > 0,
          prior_text: part > 0 ? merged : undefined,
          original_message: message,
          continuation_part: part,
        },
        t => {
          partText += t;
          setRaw(part > 0 ? merged + partText : partText);
          replyEl.append(document.createTextNode(t));
        },
        d => resolve(d),
        err => { replyEl.textContent = '⏸ ' + err; applyState('error'); resolve(null); },
      );
    });
  };

  const finishOrContinue = async (): Promise<void> => {
    if (!session) return;
    const { message, task } = session;
    continueBtn.hidden = true;

    for (;;) {
      const d = await runOnce(message, task, session.merged, session.part);
      if (!d) return;
      session.merged = session.part > 0 ? session.merged + d.text : d.text;
      setRaw(session.merged);
      renderMeta(d);
      renderArtifact(d);

      const done = d.finish_reason === 'stop' || d.merged_json_valid === true;
      if (done || !d.truncated) return;

      if (!isJsonTask(task)) {
        continueBtn.hidden = false;
        return;
      }
      session.part += 1;
      if (session.part >= MAX_AUTO_CONTINUE) {
        continueBtn.hidden = false;
        return;
      }
    }
  };

  continueBtn.addEventListener('click', () => {
    if (!session) return;
    session.part += 1;
    void finishOrContinue();
  });

  document.getElementById('raw-toggle')!.addEventListener('click', () => {
    rawPanel.classList.toggle('open');
  });
  document.getElementById('raw-copy')!.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(rawText); } catch { /* ignore */ }
  });

  ask.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || !ask.value.trim()) return;
    const message = ask.value.trim();
    ask.value = '';
    const task = detectTask(message);
    session = { message, task, merged: '', part: 0 };
    setRaw('');
    artifactEl.innerHTML = '';
    metaEl.textContent = '';
    void finishOrContinue();
  });
}
