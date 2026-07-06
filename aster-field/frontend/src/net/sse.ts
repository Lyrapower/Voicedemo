import type { StateEvent } from '../state/machine';
export function connectState(onEvent: (e: StateEvent) => void,
                             onLink: (up: boolean) => void): void {
  const es = new EventSource('/state');
  es.onopen = () => onLink(true);
  es.onmessage = (e) => onEvent(JSON.parse(e.data));
  es.onerror = () => { onLink(false); es.close(); setTimeout(() => connectState(onEvent, onLink), 3000); };
}
