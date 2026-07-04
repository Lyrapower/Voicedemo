# Paradigm reference archive

These files are **not** loaded by the active Aster deployment.

Active runtime uses only:
- `config/aster.toml`
- `local_router.db`
- `plugins/voice_age_detector/handler.py`
- `plugins/voice_age_detector/manifest.yaml`

Subdirectories:
- `carriers/` — anchor letters (守恒, 澈, 澄, Aster, etc.)
- `compiler/` — carrier_signatures.yaml, contamination_patterns.yaml
- `lyra_syncon/` — LYRA root anchor, SynCon lab specs
- `echo_prompts/` — Entry A/B system prompts and persona enforcement
- `knowledge/` — ASTER.md and mission source docs
- `proof_packs/` — 7-pack compile-layer proof reports
- `config_specs/` — legacy entry_b / entry_split JSON
- `setup_scripts/` — prompt builders and LM Studio apply scripts
- `aster/` — previous aster/ tree (Config.toml, compile.json, prompts)
- `echo_nodes_entry_a/` — Entry A Echo gateway (`:8500`) — **disabled**, `start.sh` refuses
