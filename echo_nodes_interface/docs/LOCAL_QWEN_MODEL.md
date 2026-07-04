# Local Qwen model (16 GB M2) — after 35B removal

## Removed

- **2TB:** `/Volumes/2TB/lmstudio/models/unsloth/qwen3.6-35b-a3b-ud-mlx-3bit` (~16 GB deleted)
- **LM Studio:** hub card + `model-data.json` entries for 35B
- **Chats:** Echo Nodes + Qwen 标注 now point to **`qwen/qwen3.5-9b`**

Re-run removal: `bash echo_nodes_interface/setup/remove_35b_completely.sh`

---

## Recommended model (already on your Mac)

| | |
|--|--|
| **ID** | `qwen/qwen3.5-9b` |
| **Size** | ~6.6 GB (Q4_K_M GGUF) |
| **RAM** | Comfortable on **16 GB** M2 |
| **Speed** | Much faster than 35B; no OOM crashes |
| **Path** | `~/.lmstudio/models/lmstudio-community/Qwen3.5-9B-GGUF/` |

**LM Studio:** Load `qwen/qwen3.5-9b`, Context **8192** (or 16384 if stable).

---

## Optional: MLX variant (faster on Apple Silicon)

If you want **native MLX** (often better tok/s than GGUF on M-series):

1. LM Studio → **Discover** → search **`Qwen3.5 9B MLX`**
2. Pick **4-bit MLX** from `mlx-community` or official Qwen hub entry
3. Download (~5–7 GB on internal SSD)
4. Load that model instead of GGUF

Hub examples (names may vary in UI):

- `mlx-community/Qwen3.5-9B-MLX-4bit`
- Filter: **MLX** + **9B**

CLI (if supported):

```bash
lms get qwen/qwen3.5-9b
```

---

## Do NOT use on 16 GB

| Model | Why |
|-------|-----|
| Qwen3.6 **35B** / MoE 35B | Needs ~18 GB+; you saw OOM/crash |
| Qwen3.6 **27B** MLX 4bit | Hub lists **20 GB** minimum |
| Qwen3 **80B** Next | 42 GB+ minimum |

---

## Entry A (Echo Nodes) + Entry B (标注)

Both conversations now use **`qwen/qwen3.5-9b`**.

- **Echo Nodes Interface:** keeps long system prompt; use **8192** context
- **Qwen 35B（标注）:** rename in UI if you like; model is 9B now

Update install script default:

```bash
# edit install_lmstudio_dual_entry.sh
MODEL_ID="qwen/qwen3.5-9b"
CONTEXT_TOKENS=8192
```
