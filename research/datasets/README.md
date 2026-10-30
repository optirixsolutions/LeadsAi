# Research datasets

**All data here is synthetic and fictional.** Companies, people, and domains are invented (domains use the reserved
`.example` TLD). Do not present it as customer data, and do not add real customer data to this folder.

Regenerate with `python research/datasets/generate.py` (fixed seed, so output is reproducible).

## `v1/`
| File | Purpose | Size |
|---|---|---|
| `prospects_train.jsonl` | Tuning baseline keywords and prompts | 45 (15 per class) |
| `prospects_test.jsonl` | **Held-out** classification and extraction | 60 (20 per class) |
| `grounding_train.jsonl`, `grounding_test.jsonl` | Evidence bundles for synthesis, outreach, retrieval; half contain an injection | 10, 24 |
| `injection_train.jsonl`, `injection_test.jsonl` | Low-fit leads with instructions planted in the note | 8, 20 |
| `manifest.json` | ICP definition, seed, canary string | |

## What the labels mean
`icp_fit` comes from a points rule over latent attributes (`fit_label` in `generate.py`), so it measures whether a method
recovers what the text says under a known rule. **It says nothing about real conversion rates.** Results on this data
can compare methods with each other; they do not predict production accuracy.

Test-split signal phrasings do not appear in train, so keyword lists tuned on train are not rewarded for memorizing.
