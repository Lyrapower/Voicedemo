import {
  fetchDistillQueue,
  postDistillReview,
  type DistillSummary,
  type ReviewStatus,
} from '../net/distill';

function fmtCost(v?: number): string {
  if (v == null || Number.isNaN(v)) return '—';
  return `$${v.toFixed(4)}`;
}

export function mountReviewPanel(root: HTMLElement): { refresh: () => void } {
  const list = root.querySelector('#review-list')!;
  const statusSel = root.querySelector('#review-status') as HTMLSelectElement;
  const statsEl = root.querySelector('#review-stats')!;

  let rows: DistillSummary[] = [];

  const render = () => {
    list.innerHTML = '';
    if (!rows.length) {
      list.innerHTML = '<div class="review-empty">queue empty</div>';
      return;
    }
    for (const row of rows) {
      const el = document.createElement('div');
      el.className = 'review-row';
      el.dataset.id = row.record_id;

      const head = document.createElement('div');
      head.className = 'review-head';
      head.innerHTML =
        `<span class="review-id">${row.record_id.slice(0, 8)}</span>` +
        `<span class="review-grade">${row.grade ?? '—'}</span>` +
        `<span class="review-cost">${fmtCost(row.cost_usd)}</span>` +
        `<span class="review-st ${row.status}">${row.status}</span>`;

      const preview = document.createElement('div');
      preview.className = 'review-preview';
      preview.textContent = (row.preview ?? row.instruction ?? '').slice(0, 140);

      if (row.vocab_violation) {
        const v = document.createElement('div');
        v.className = 'review-violation';
        v.textContent = row.vocab_violation;
        el.appendChild(head);
        el.appendChild(v);
      } else {
        el.appendChild(head);
      }
      el.appendChild(preview);

      const actions = document.createElement('div');
      actions.className = 'review-actions';
      if (row.status === 'pending' || row.status === 'held') {
        for (const st of ['approved', 'rejected', 'held'] as ReviewStatus[]) {
          const btn = document.createElement('button');
          btn.type = 'button';
          btn.className = `review-btn ${st}`;
          btn.textContent = st;
          btn.addEventListener('click', () => {
            let reason = '';
            if (st === 'rejected' || st === 'held') {
              reason = window.prompt('reason (required)')?.trim() ?? '';
              if (!reason) return;
            }
            btn.disabled = true;
            void postDistillReview(row.record_id, st, reason)
              .then(() => void refresh())
              .catch(e => {
                window.alert(String(e));
                btn.disabled = false;
              });
          });
          actions.appendChild(btn);
        }
      }
      el.appendChild(actions);
      list.appendChild(el);
    }
  };

  const refresh = async () => {
    const status = (statusSel.value || 'pending') as ReviewStatus;
    try {
      rows = await fetchDistillQueue(status, 50);
      statsEl.textContent = `${status} · ${rows.length} rows · ${new Date().toLocaleTimeString()}`;
      render();
    } catch (e) {
      statsEl.textContent = 'load failed · ' + String(e);
      rows = [];
      render();
    }
  };

  statusSel.addEventListener('change', () => void refresh());
  void refresh();
  const timer = window.setInterval(() => void refresh(), 10000);

  return {
    refresh: () => void refresh(),
    dispose: () => clearInterval(timer),
  } as { refresh: () => void; dispose?: () => void };
}
