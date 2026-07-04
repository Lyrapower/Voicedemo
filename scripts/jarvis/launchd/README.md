# Jarvis launchd templates (dry-run / Disabled)

Ship **Disabled=true**. Enable only after reviewing `deliver/jarvis/JARVIS_MERGE_MAP.md`.

## Install (optional — stays disabled)

```bash
mkdir -p ~/Library/LaunchAgents logs/jarvis_tasks
cp scripts/jarvis/launchd/com.demo.jarvis.*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.demo.jarvis.crypto-scan-dryrun.plist
```

## Manual run (preferred while testing)

```bash
./scripts/jarvis_run_task.sh --list
./scripts/jarvis_run_task.sh aether.snapshot.readonly --dry-run
./scripts/jarvis_run_task.sh crypto.scan.dryrun --dry-run
```

Or via platform_main (must be running on 127.0.0.1:8686):

```bash
curl -X POST 'http://127.0.0.1:8686/api/jarvis/tasks/crypto.scan.dryrun/run?dry_run=true'
```

## Rollback

```bash
launchctl unload ~/Library/LaunchAgents/com.demo.jarvis.crypto-scan-dryrun.plist 2>/dev/null || true
rm -f ~/Library/LaunchAgents/com.demo.jarvis.*.plist
```

No Aster/Grid/Tailscale ports are modified by these plists.
