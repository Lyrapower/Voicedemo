# Voice Bridge

Do not make voice a new agent.

```text
audio in
 -> OpenAI Realtime / other speech bridge
 -> transcript
 -> POST /events/voice
 -> existing harness
 -> response text
 -> speech provider
 -> audio out
```

## Boundaries

- Voice provider owns no long-term memory.
- Voice provider does not select the persistent worker.
- Voice provider receives only the minimum context needed.
- Tools still execute through the harness.

## Claude tag

Spoken:

```text
Grid, ask Claude Code to review this diff.
```

Normalize to a normal durable job:

```json
{
  "channel":"voice",
  "worker":"cc",
  "goal":"Review the current diff",
  "cloud_allowed":false
}
```

No special voice-only execution path.
