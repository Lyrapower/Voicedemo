export type TaskType = 'chat' | 'diary' | 'compile_json' | 'handoff_protocol';

export interface JsonArtifact {
  ok: boolean;
  json?: unknown;
  status?: string;
  merged_json_valid?: boolean;
  error?: string;
}

export interface ChatDone {
  done: true;
  served_by: string | null;
  finish_reason: string | null;
  truncated: boolean;
  transport_truncated?: boolean;
  text: string;
  task_type?: TaskType;
  max_tokens?: number;
  continuation_part?: number;
  artifact?: JsonArtifact;
  merged_json_valid?: boolean;
  status?: string;
  contract_flag?: string | null;
}

export interface ChatRequest {
  message: string;
  task_type?: TaskType;
  continue?: boolean;
  prior_text?: string;
  original_message?: string;
  continuation_part?: number;
}

export async function sendChat(
  req: ChatRequest,
  onToken: (t: string) => void,
  onDone: (d: ChatDone) => void,
  onError: (e: string) => void,
): Promise<void> {
  try {
    const r = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    const reader = r.body!.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf('\n\n')) >= 0) {
        const line = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        if (!line.startsWith('data:')) continue;
        const d = JSON.parse(line.slice(5));
        if (d.token) onToken(d.token);
        if (d.done) onDone(d as ChatDone);
        if (d.error) onError(d.error);
      }
    }
  } catch {
    onError('bridge unreachable');
  }
}
