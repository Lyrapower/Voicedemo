# Agent Payment Risk Note

generated_at: 2026-07-02T03:26:40Z

## Wallet permission risks
- Agent scope creep into signing or custody
- Over-broad wallet permissions for automation
- Missing human approval on high-value requests

## Programmable payment risks
- Payment intent replay or mis-routing
- Streaming / subscription rails abused by agents
- Weak separation between advisory and execution paths

## Stablecoin flow risks
- Issuer / counterparty concentration
- Redemption delay during stress
- Cross-rail settlement assumptions unverified

## Identity / compliance risks
- KYC/AML boundaries unclear for agent-mediated flows
- Attestation trust without verifier independence
- Cross-border exposure unknown without counsel

## Automation abuse risks
- Autonomous payment loops without kill switch
- Prompt injection leading to payment intent changes
- Missing audit log for agent payment decisions

## Mitigation checklist
- [ ] No wallet connection in V1 module
- [ ] Human gate on any execution path
- [ ] Separate research vs verified action zones
- [ ] Log all agent payment recommendations
- [ ] Route high-risk items to 澄 review
- [ ] No investment advice or live price claims
