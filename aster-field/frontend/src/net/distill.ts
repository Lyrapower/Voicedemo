export type ReviewStatus = 'pending' | 'approved' | 'rejected' | 'held';

export interface DistillSummary {
  record_id: string;
  compile_ts?: string;
  node_id?: string;
  task?: string;
  client?: string;
  status: ReviewStatus;
  grade?: string;
  preview?: string;
  cost_usd?: number;
  duration_ms?: number;
  skip_reason?: string;
  coach_json_ok?: boolean;
  vocab_violation?: string;
  instruction?: string;
  student_draft?: string;
  coach?: Record<string, unknown>;
  compile_semantics?: string;
  test?: boolean;
  allow_draft_override?: boolean;
}

export interface DistillRecordDetail extends DistillSummary {
  coach_raw?: string;
  cli_meta?: Record<string, unknown>;
  decisions?: Array<Record<string, unknown>>;
}

export interface CoachResult {
  ok?: boolean;
  skipped?: boolean;
  skip_reason?: string;
  record_id?: string;
  record?: DistillRecordDetail;
  cost_usd?: number;
  duration_ms?: number;
}

export async function fetchDistillQueue(
  status: ReviewStatus | 'pending' = 'pending',
  limit = 50,
): Promise<DistillSummary[]> {
  const q = new URLSearchParams({ status, limit: String(limit) });
  const r = await fetch(`/distill/queue?${q}`);
  if (!r.ok) throw new Error(`queue ${r.status}`);
  const j = (await r.json()) as { rows?: DistillSummary[] };
  return j.rows ?? [];
}

export async function fetchDistillRecent(limit = 10): Promise<DistillSummary[]> {
  const r = await fetch(`/distill/recent?limit=${limit}`);
  if (!r.ok) throw new Error(`recent ${r.status}`);
  const j = (await r.json()) as { records?: DistillSummary[] };
  return j.records ?? [];
}

export async function fetchDistillRecord(recordId: string): Promise<DistillRecordDetail | null> {
  const r = await fetch(`/distill/record/${encodeURIComponent(recordId)}`);
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`record ${r.status}`);
  return (await r.json()) as DistillRecordDetail;
}

export async function postDistillReview(
  recordId: string,
  status: ReviewStatus,
  reason = '',
): Promise<{ current_status: ReviewStatus }> {
  const r = await fetch('/distill/review', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ record_id: recordId, status, reason, via: 'tab3' }),
  });
  const j = await r.json();
  if (!r.ok) throw new Error(String(j.error ?? r.status));
  return j as { current_status: ReviewStatus };
}

export async function sendCoach(
  instruction: string,
  draft: string,
  task?: string,
  opts?: { allowDraft?: boolean; compileSemantics?: string },
): Promise<CoachResult> {
  const r = await fetch('/chat/coach', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      instruction,
      draft,
      task_type: task,
      allow_draft: !!opts?.allowDraft,
      compile_semantics: opts?.compileSemantics,
    }),
  });
  const j = (await r.json()) as CoachResult & { error?: string };
  if (!r.ok) throw new Error(j.error ?? `coach ${r.status}`);
  return j;
}
