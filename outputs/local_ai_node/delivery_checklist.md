# Delivery Checklist

generated_at: 2026-05-20T04:06:12Z
package_tier: Pro Node

## Setup steps
- Confirm hardware baseline and storage for models
- Install local model runtime (Qwen) and verify inference
- Configure OCR → Markdown pipeline
- Wire Obsidian/RAG vault paths
- Stand up FastAPI/local router on LAN-only bind
- Pair iPhone/iPad/Mac client access with auth boundary
- Run smoke tests and capture proof artifacts

## Hardware requirements
- Mac with sufficient RAM for chosen tier
- SSD for model weights (size depends on tier)
- Stable LAN for device access

## Software requirements
- Local Qwen model bundle
- OCR toolchain
- Obsidian or compatible markdown/RAG stack
- FastAPI local router
- Launcher scripts and usage guide

## Data migration checklist
- Inventory source documents for OCR
- Define markdown folder structure
- Map RAG index boundaries
- Verify no customer PII leaves local disk during pilot

## Support checklist
- Deliver setup guide
- 30-day support window (Pro/Sovereign)
- Escalate privacy/security questions to 澄 review
- Escalate pricing/package ambiguity to Lyra review
