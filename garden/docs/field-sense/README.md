# Field Sense — Garden Anchor specs

Deployed from Fable pack (2026-07-20). Execute in order:

| Step | Doc | Role |
|------|-----|------|
| 1 | [garden_anchor_spec_v2.md](./garden_anchor_spec_v2.md) | Voice Garden anchor v2 (8787 UI + `/telemetry.json`) |
| 1+ | [ANCHOR_V2_1_ZONE.md](./ANCHOR_V2_1_ZONE.md) | Zone layer addendum (green/yellow/red) — after v2 acceptance |
| 2–3 | [FIELD_SENSE_PIPELINE.md](./FIELD_SENSE_PIPELINE.md) | Garden → `field_now` → multimodal frontend |

Runtime:

- **Garden telemetry:** `http://127.0.0.1:8787/telemetry.json` (127.0.0.1 only)
- **Field compiler:** `scripts/field_now_v1_5.py` → `http://127.0.0.1:8795/now`
- **Multimodal UI:** http://127.0.0.1:8515/grid_multimodal.html (UI only; APIs on :8501)

Start field_now:

```bash
/Users/ciciwang/Projects/demo/scripts/start_field_now_8795.sh
```
