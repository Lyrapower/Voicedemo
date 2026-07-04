# Deployment Options

Start with the lowest-risk deployment that proves value. Do not overbuild infrastructure before the workflow is validated.

## Option A - Local Proof

- Best for: Early validation, hackathon demos, grant proof, internal workflow review.
- Requirements:
  - local machine or repo access
  - sample data
  - no production keys
  - no custody

## Option B - Private Cloud

- Best for: Small team usage, investor demos, controlled external access.
- Requirements:
  - approved cloud account
  - environment variables
  - explicit API budget
  - access control owner

## Option C - Client Infrastructure

- Best for: Teams with existing DevOps/security requirements.
- Requirements:
  - client-provided repo/cloud
  - deployment contact
  - environment policy
  - approval process

## Option D - Hybrid / Router-Based

- Best for: Teams that need local-first behavior with optional external model/API routing.
- Requirements:
  - routing policy
  - budget cap
  - kill switch
  - audit log
  - approved external endpoints

## Deployment Quiz

- Choose Local Proof if:
  - you are not sure the workflow is worth productionizing yet
  - you need demo/proof quickly
  - you do not want external exposure

- Choose Private Cloud if:
  - multiple team members need access
  - demo needs public URL
  - external users must test

- Choose Client Infrastructure if:
  - security policy requires internal ownership
  - procurement/compliance requires client environment

- Choose Hybrid Router if:
  - local-first is required
  - external APIs may be useful but must be controlled
