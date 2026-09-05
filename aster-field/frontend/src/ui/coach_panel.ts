import {
  fetchDistillRecent,
  sendCoach,
  type DistillSummary,
} from '../net/distill';

function fmtCost(v?: number): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `$${v.toFixed(4)}`;
}

function fmtRecord(rec: DistillSummary): string {
  const id = rec.record_id.slice(0, 8);
  const gate = rec.vocab_violation ? `held · ${rec.vocab_violation}` : rec.status;
  const grade = rec.grade ?? '—';
  const cost = fmtCost(rec.cost_usd);
  const draftTag = rec.compile_semantics === 'parse_only' ? ' · draft' : '';
  const preview = (rec.preview ?? '').slice(0, 80);
  return `[${id}] ${gate} · ${grade} · ${cost}${draftTag}\n  ${preview || '(no preview)'}`;
}

export function mountCoachPanel(root: HTMLElement): { refresh: () => void } {
  const ins = root.querySelector('#coach-ins') as HTMLTextAreaElement;
  const draft = root.querySelector('#coach-draft') as HTMLTextAreaElement;
  const log = root.querySelector('#coach-log') as HTMLPreElement;
  const sendBtn = root.querySelector('#coach-send') as HTMLButtonElement;
  const loadBtn = root.querySelector('#coach-load-compile') as HTMLButtonElement;

  let recent: DistillSummary[] = [];

  const renderLog = (head: string, tail?: string) => {
    const lines = [head];
    if (recent.length) {
      lines.push('', '— recent records —');
      for (const r of recent) lines.push(fmtRecord(r));
    }
    if (tail) lines.push('', tail);
    log.textContent = lines.join('\n');
  };

  const refresh = async () => {
    try {
      recent = await fetchDistillRecent(8);
      renderLog('poll ok · ' + new Date().toLocaleTimeString());
    } catch (e) {
      renderLog('poll failed · ' + String(e));
    }
  };

  loadBtn.addEventListener('click', () => {
    void fetch('/distill/latest_compile')
      .then(r => r.json())
      .then(j => {
        if (j.instruction || j.draft) {
          ins.value = j.instruction ?? '';
          draft.value = j.draft ?? '';
          const sem = String(j.semantics ?? '');
          renderLog(
            'loaded compile · ' +
              String(j.record_id ?? '').slice(0, 8) +
              (sem === 'parse_only' ? ' · draft' : ''),
          );
          return;
        }
        throw new Error('empty');
      })
      .catch(() => {
        const hit = recent.find(r =>
          r.task === 'compile_json' || r.task === 'handoff_protocol' || r.node_id === 'field-compile',
        );
        if (hit) {
          ins.value = hit.instruction ?? '';
          draft.value = hit.student_draft ?? '';
          renderLog('loaded from recent ' + hit.record_id.slice(0, 8));
          return;
        }
        renderLog('no compile record — run compile first');
      });
  });

  sendBtn.addEventListener('click', () => {
    const instruction = ins.value.trim();
    const d = draft.value.trim();
    if (!d) {
      renderLog('draft required');
      return;
    }
    sendBtn.disabled = true;
    renderLog('sending Fable coach…');
    void sendCoach(instruction, d)
      .then(res => {
        const rec = res.record;
        const gate = rec?.vocab_violation
          ? `gate: held · ${rec.vocab_violation}`
          : `gate: ${rec?.status ?? 'pending'}`;
        const cost = fmtCost(rec?.cost_usd ?? res.cost_usd);
        const grade = rec?.grade ?? '—';
        const coach = rec?.coach;
        let coachLine = '';
        if (coach && typeof coach === 'object') {
          const ft = coach.failure_type ?? coach.comment ?? JSON.stringify(coach).slice(0, 120);
          coachLine = `\ncoach: ${String(ft).slice(0, 200)}`;
        }
        renderLog(
          `done · ${rec?.record_id?.slice(0, 8) ?? '?'} · ${grade} · ${cost} · ${gate}${coachLine}`,
        );
        void refresh();
      })
      .catch(e => renderLog('coach failed · ' + String(e)))
      .finally(() => {
        sendBtn.disabled = false;
      });
  });

  void refresh();
  const timer = window.setInterval(() => void refresh(), 8000);

  return {
    refresh: () => {
      void refresh();
    },
    dispose: () => clearInterval(timer),
  } as { refresh: () => void; dispose?: () => void };
}
