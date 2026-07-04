# Agent Roles Plan

generated_at: 2026-05-20T04:06:12Z

## Qwen (local)
- Run on-device inference for private workflows
- Never exfiltrate customer documents

## Cursor
- Execute implementation tasks against local repo
- Generate and update delivery artifacts

## GPT/Claude API (sanitized review)
- Optional external review on redacted summaries only
- Disabled by default in V1 module actions

## 澄 (audit)
- Review privacy/security flags
- Triggered: True

## Lyra (authority)
- Resolve product/pricing ambiguity
- Triggered: False

## Module bans
- No payment connection
- No hardware purchase
- No fake compatibility promises
