# AI Strategy and Evaluation

Status: design only. Implementation starts in Phase 4.

## Provider abstraction
`app/agents/llm/` (Phase 4) defines a provider-independent interface with adapters for hosted providers, a local
Ollama-compatible endpoint, and a deterministic **mock** provider used by default in tests and when no key is configured.

Each model configuration records: provider, model ID, capabilities (structured output, tool calling, embeddings),
context limit, input/output price, timeout, retry policy, concurrency limit, fallback, availability.

Routing is per task type (classification, extraction, research synthesis, drafting, embeddings) and considers capability,
quality from evaluations, latency, and budget. A fallback may never downgrade a security check or fabricate success.
Consequential actions are gated by deterministic permission checks and human approval, never model confidence.

## Evaluation record
Every run stores: task type, dataset version, model + config, prompt version, input/output tokens, latency, estimated cost,
schema validity, grounding score, human rating (optional), failure category.

## Method
1. Synthetic, clearly labelled fictional B2B prospect dataset with labelled train/held-out splits.
2. Deterministic baseline (rules for ICP fit and scoring) before any model comparison.
3. Compare models on held-out data only; report measured numbers with sample sizes.
4. Grounding check: every claim in a research brief or draft must cite stored evidence IDs; unsupported claims fail.
5. Prompt-injection suite: imported content containing instructions must not change tool use or output policy.
6. No fine-tuning until baseline evaluation shows a measured gap it would close.

No accuracy, precision, recall, cost, or savings figure is reported without an actual measurement behind it.
