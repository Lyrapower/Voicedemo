# Qwen MLX dense — larger than 9B (M2 16GB)

**Note:** Echo Nodes / compile layer configs are **not** pinned here — you will merge into one entry and edit files yourself.

---

## Size ladder (dense MLX only)

| Model | HF | Disk | 16 GB M2 | Role |
|-------|-----|------|----------|------|
| 9B 4bit | [Qwen3.5-9B-MLX-4bit](https://huggingface.co/mlx-community/Qwen3.5-9B-MLX-4bit) | ~6 GB | Stable | Too small for you |
| **14B 4bit (Qwen3)** | [mlx-community/Qwen3-14B-4bit](https://huggingface.co/mlx-community/Qwen3-14B-4bit) | **~8.3 GB** | **Best fit** | Largest **realistic** step up on 16 GB |
| 27B 4bit (Qwen3.5) | [mlx-community/Qwen3.5-27B-4bit](https://huggingface.co/mlx-community/Qwen3.5-27B-4bit) | **~16 GB** | **Tight / often OOM** | Newest dense; same class of pain as 35B |

There is **no official Qwen3.5 dense 14B** in mlx-community today — gap is **9B → 27B**.

---

## Recommendation

### 1) Default pick on your hardware: **Qwen3-14B MLX 4bit**

- **Dense**, **MLX**, clearly stronger than 9B for compile / long reasoning  
- ~8.3 GB weights → usually **~10–12 GB** peak with context on 16 GB (workable with **4096–8192** context)  
- Store on **2TB** if internal SSD is tight  

```bash
lms get "https://huggingface.co/mlx-community/Qwen3-14B-4bit" --mlx -y
```

LM Studio load: **Context 8192**, Thinking **off**, quit heavy apps.

Also fine: [lmstudio-community/Qwen3-14B-MLX-4bit](https://huggingface.co/lmstudio-community/Qwen3-14B-MLX-4bit) (same class).

---

### 2) If you insist on “much bigger”: **Qwen3.5-27B MLX 4bit**

- Newer **Qwen3.5** dense line; better for coding / compile quality  
- Weights alone **~16.1 GB** → on **16 GB unified memory** you will often hit the same **Metal OOM / chat crash** as 35B unless:
  - Context **≤ 4096** (sometimes **2048**)
  - Only LM Studio running
  - Accept swap / slowness  

```bash
lms get "https://huggingface.co/mlx-community/Qwen3.5-27B-4bit" --mlx -y
```

**Honest verdict:** 27B is the right **disk size** on 2TB, wrong **RAM class** for M2 16GB as a daily driver. **24 GB+ Mac** → 27B is the target.

---

## Not recommended (16 GB)

| Model | Why |
|-------|-----|
| Qwen3.6 35B MoE | Removed; ~18 GB+ |
| Qwen3.5 35B-A3B MoE | Same family as old crash |
| nightmedia 9B merges | Not dense baseline; odd peaks |
| Qwen3.5 27B **8bit** | ~29 GB — needs 48 GB+ class machine |

---

## After you merge Echo + compile (one entry)

When you wire the single entry yourself:

1. Pick **14B** for stability or **27B** for max quality (experimental on 16 GB)  
2. One system prompt; one `contextLength` (start **8192** for 14B, **4096** for 27B)  
3. Download to **2TB** if needed: set LM Studio models folder or symlink weights there  

No changes required under `incoming/echo_nodes/` until your merge is ready.
