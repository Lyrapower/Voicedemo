# CC sandbox (docker) · 2026-09-07

cc worker runs in `grid-cc:2.1.201` on internal net `grid-cc-net`.
Host 8501 / 8630 / store are unreachable from the container.
Narrow bridge is `grid-cc-fwd` only: Ollama :11434 + EGRESS.md approved https :443.

## Image / net / mounts

| 项 | 值 |
|---|---|
| image | `grid-cc:2.1.201` (`node:22-slim` + `@anthropic-ai/claude-code@2.1.201`) |
| fwd image | `grid-cc-fwd:local` (alpine + socat + stdlib CONNECT proxy) |
| network | `grid-cc-net` (`--internal`) |
| fwd | `grid-cc-fwd` on grid-cc-net and default bridge; **no host port bind** |
| job files | `-v <job>:/ws/job:ro` copied into tmpfs `/work` |
| add-dir | `-v <path>:/ws/pN:ro` |
| writable | `--tmpfs /work`; rootfs **not** `--read-only`（v7 二分：`--read-only` 下 claude 静默 exit 0；去掉后出字） |
| env | `ANTHROPIC_AUTH_TOKEN=ollama` `ANTHROPIC_BASE_URL=http://grid-cc-fwd:11434` `HOME=/work` `PATH=…` + HTTPS_PROXY to fwd:3128 |

## Rollback

```
docker rm -f grid-cc-fwd
docker network rm grid-cc-net
docker rmi grid-cc:2.1.201 grid-cc-fwd:local
```

Missing sandbox → cc job `BLOCKED_SANDBOX_MISSING`. No host claude fallback.
`sandbox_required=false` is not a legal rollback.
