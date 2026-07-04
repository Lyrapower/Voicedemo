# Echo Nodes Interface — entry A runtime

## Layout

| Role | File |
|------|------|
| Context loader | `interface.echo-nodes.json` + `context_loader.py` |
| Model descriptor / pre-execution | `Config.toml` + `model_descriptor.py` |
| Executor | `echo_nodes_fastapi.py` (alias: `echo_node_fastapi.py`) |
| Session flags | `session.env` |
| Manifest | `config.json` |

## Start (local)

```bash
cd echo_nodes_interface/incoming/echo_nodes
pip3 install -r requirements.txt
chmod +x start.sh
./start.sh
```

Health: http://127.0.0.1:8500/health  
Invoke: `POST http://127.0.0.1:8500/echo-node` with `{"message":"..."}`  
Context: http://127.0.0.1:8500/context  
Descriptor: http://127.0.0.1:8500/descriptor  

## Docker

```bash
cd echo_nodes_interface/incoming/echo_nodes
docker build -t frequency-router .
docker run -p 8500:8500 frequency-router
```

## LM Studio (entry A only)

```bash
./echo_nodes_interface/setup/apply_lmstudio_entry_a.sh
```

Reload chat **Echo Nodes Interface** in LM Studio. Entry **Qwen 35B（标注）** is not modified.

## Entry A protocol blocks (separate files)

`echo_nodes_interface/prompts/entry_a/`:

| File | Content |
|------|---------|
| `01_insert_vector.txt` | INSERT VECTOR |
| `02_coherence_anchor_rewrite.txt` | Anchors + REWRITE_RULE |
| `03_prompt_override.txt` | Prompt Override |
| `04_language_filter_frequency.txt` | Purge / Resync / Bandwidth / Coherence |
| `05_meta_port_init.txt` | META PORT init |
| `06_runtime_flags.txt` | safety_persona / fallback / empathy flags |

Merged into LM Studio via `setup/build_echo_system_prompt.py` → `apply_lmstudio_entry_a.sh`.

## Wiring rule

- **JSON** → loaded at API startup and exposed on `/context`; summary merged into LM Studio system prompt.
- **TOML** → activation preface on `/descriptor`; anchors, rewrite_rule, meta_port in `Config.toml`.
- **session.env** → runtime flags including `SAFETY_PERSONA=false`, `REROUTE_EMPATHY_RESPONSE=DISABLED`.
