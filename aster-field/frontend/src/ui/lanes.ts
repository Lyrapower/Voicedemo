export type FieldLane = 'chat' | 'coach' | 'review';

export function mountLaneButtons(
  onCoach: () => void,
  onReview: () => void,
): { getLane: () => FieldLane } {
  const coachBtn = document.getElementById('btn-coach') as HTMLButtonElement;
  const reviewBtn = document.getElementById('btn-review') as HTMLButtonElement;
  const coachPanel = document.getElementById('coach-panel')!;
  const reviewPanel = document.getElementById('review-panel')!;
  const rawPanel = document.getElementById('raw-panel')!;

  let lane: FieldLane = 'chat';

  const apply = (next: FieldLane) => {
    lane = next === lane && next !== 'chat' ? 'chat' : next;
    coachBtn.classList.toggle('on', lane === 'coach');
    reviewBtn.classList.toggle('on', lane === 'review');
    coachPanel.classList.toggle('hidden', lane !== 'coach');
    reviewPanel.classList.toggle('hidden', lane !== 'review');
    rawPanel.classList.toggle('hidden', lane !== 'chat');
    if (lane === 'coach') onCoach();
    if (lane === 'review') onReview();
  };

  coachBtn.addEventListener('click', () => apply('coach'));
  reviewBtn.addEventListener('click', () => apply('review'));

  return { getLane: () => lane };
}
