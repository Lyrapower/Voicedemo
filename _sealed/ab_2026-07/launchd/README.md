# Launchd tombstones · A/B lane teardown

| Label | Status | Sealed |
|---|---|---|
| `com.demo.aether.premarket-compile` | DISABLED 2026-07-20 | `com.demo.aether.premarket-compile.plist.DISABLED-2026-07-21` |
| `com.demo.aether.premarket-sonnet` | unload only | plist may remain in LaunchAgents |
| `com.demo.aether.offpool-coach` | unload only | Fable coach channel |

`scripts/start_premarket_compile_gated.sh` exits 0 with tombstone message; no new `aether_premarket_grid` emits.
