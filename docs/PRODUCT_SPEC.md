# Product Specification

**SalesIQ** — autonomous revenue intelligence and sales automation.
Positioning: *turn fragmented sales workflows into an intelligent, evidence-driven revenue engine.*

## Users
| Role | Needs |
|---|---|
| Sales rep | Prioritized leads, evidence-backed context, drafted outreach, next actions |
| Sales manager | Pipeline health, stale deals, team activity, approval queue |
| Revenue ops / admin | ICP and scoring configuration, integrations, usage limits, audit |
| Analyst (read-only) | Conversion, source performance, outcome analysis |

## Lifecycle covered
Import → research → enrich → ICP fit → score → buying signals → draft outreach → follow-ups → opportunities → campaign
and pipeline tracking → outcome analysis → controlled improvement from verified results.

## Principles
- Evidence before inference: every material claim links to a stored source; inferences are labelled.
- Recommendations are distinct from actions. Agents research, classify, draft, and recommend; sending, launching, and
  consequential changes require explicit approval and a server-side policy check.
- Deterministic rules where possible; models only where measured to add value.
- Scores are explainable and are not presented as conversion probabilities unless calibrated against outcome data.
- No fabricated contacts, sources, signals, metrics, or revenue attribution.
- Transparent model cost; tenant-level quotas.

## Core modules
Overview · Lead intelligence · Lead profile · Pipeline (board + table) · Agent control center · Outreach workspace ·
Analytics · Integrations · Settings (org, team, roles, ICP, scoring, agents, models, usage, security, billing).

## Out of scope for initial release
Fine-tuning foundation models; purchased or scraped personal data; autonomous sending without approval; real payment
processing without provider credentials (a development-only billing adapter is used instead).
