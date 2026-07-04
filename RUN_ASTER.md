# Aster — single entry

Active only:
- `config/aster.toml`
- `local_router.db`
- `plugins/voice_age_detector/`

```bash
/Users/ciciwang/Desktop/demo/scripts/start_aster.sh
```

LM Studio（直接覆盖旧 tab，不合并 archive）：

```bash
/Users/ciciwang/Desktop/demo/scripts/deploy_lmstudio.sh
```

然后 **完全退出并重启 LM Studio**，Load `qwen2.5-1.5b`，用 **Aster** tab。

Open particle UI: `http://127.0.0.1:8787/` (port from `[channel]` in aster.toml)

Init DB: `scripts/init_local_router_db.sh`

No Entry A / Entry B. Archived: `archive/paradigm_documentation/`
