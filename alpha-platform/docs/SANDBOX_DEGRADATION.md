# Alpha Factory Sandbox · Platform Degradation Notes · 2026-07-27

## Target (V1.2/V1.3)

- AST static scan + restricted `__builtins__`
- Subprocess isolation (`spawn`) + CPU timeout 120s + memory 1GB (`RLIMIT_AS`)
- tempdir workspace; data db read-only URI
- Network namespace `unshare` / seccomp block

## macOS / Docker (this deployment)

| Control | Status | Residual risk |
|---------|--------|---------------|
| AST static scan | **Active** | Dynamic string eval without AST-visible call may evade (mitigated by restricted builtins) |
| Restricted builtins in exec | **Active** | Subprocess still has full Python if AST+builtins both bypassed |
| spawn subprocess | **Active** | Parent DB path read-only mount |
| CPU timeout 120s | **Active** | |
| Memory 1GB RLIMIT_AS | **Best-effort** | macOS/Docker may ignore or soften AS limit |
| unshare network | **Not available** | No network syscall block; rely on no socket imports + AST |
| seccomp | **Not configured** | Documented gap |

## Contract

- df schema: `schemas/factory_df_contract.json`
- fix_error grey-zone column whitelist = `column_whitelist` in that file

## When Linux bare-metal available

Re-evaluate: `unshare -n` wrapper, seccomp-bpf deny `connect`/`socket`, cgroups v2 memory max.
