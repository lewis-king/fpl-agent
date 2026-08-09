# Qwen3.5-4B FPL candidate v4: correction run and selection

Date: 4 August 2026  
Status: trained and evaluated; **not promoted**

## Outcome

V4 is a reproducible, targeted correction experiment, but it is not the deployment winner. It
raised complete text-contract passes from 6/37 to 8/37 and kept clean turn termination, while
regressing exact tool routing and argument validity. It was exact on the supplied mobile team
image but emitted duplicate starter slots on desktop, making that import invalid. Retain v4 for
failure analysis; keep v3 as the current guarded screenshot adapter and do not yet promote any
adapter as the autonomous chatbot backbone.

## Data and training record

V4 trained from clean `unsloth/Qwen3.5-4B`; it was not stacked on v3. The objective covered only
assistant responses and tool calls, with the vision encoder frozen.

| Item | Result |
| --- | --- |
| Training data | 13,600 rows: 9,600 broad replay + 4,000 corrections |
| Correction families | language 1,200; tool route 1,000; decision route 800; safety 400; multilingual 200; formation images 400 |
| Image / tool rows | 1,360 / 7,240 |
| Method | BF16 LoRA, rank 16, alpha 16 |
| Effective batch | 16 (batch 2, gradient accumulation 8) |
| Epochs / optimizer steps | 1 / 850 |
| Learning rate | 0.00002, linear schedule |
| Wall time | 1,896.66 seconds (31 minutes 37 seconds) |
| Peak reserved VRAM | 22,242,394,112 bytes (20.71 GiB) |
| Final train loss | 0.157946 |
| Final adapter size | 144 MiB on disk |

The data hash is
`81eff59fa173bf36cf9dd1334199b517ab2e83374fd44b3c6079f1babc84d4db`; the config hash is
`7cbeedb668711fc50921ac9b7e08ab62db6fd99fa0198a56c65d3a02ad6eb8a0`. Five checkpoints were
written at steps 170, 340, 510, 680 and 850. Checkpoint 510 was explicitly evaluated and did not
beat the final adapter, so further checkpoint sweeps were not justified.

## Corrected text evaluation

All three models received the same 37 prompts, integer manager-ID schemas, fixed synthetic tool
results, and `<|im_end|>` generation stop. The evaluator tests routing and response contracts, not
live FPL factual correctness.

| Measure | Base 4B | v3 | v4 final | v4 step 510 |
| --- | ---: | ---: | ---: | ---: |
| Exact tool route | 16/37 | **21/37** | 14/37 | 13/37 |
| Valid tool arguments | **37/37** | 36/37 | 34/37 | 33/37 |
| Strict lexical response contract | **10/37** | 7/37 | 9/37 | 9/37 |
| Clean turn boundary | 37/37 | 37/37 | 37/37 | 37/37 |
| All four checks | 6/37 | 6/37 | **8/37** | 7/37 |

The two extra complete cases are real but insufficient for promotion. V4 lost seven exact routes
relative to v3 and three valid argument objects relative to base. Multilingual, prompt-injection,
ambiguity and staleness categories still had zero fully passing cases. The lexical checker remains
deliberately conservative, so a future benchmark should add semantic and human review; route and
schema failures remain objective blockers.

## Real screenshot evaluation

The same corrected prompt was run against the checksum-pinned mobile and desktop screenshots. The
downstream importer resolved visible names against the current catalog, derived formation from
starter positions, enforced legal squad rules and kept the result provisional.

| Candidate | Mobile | Desktop |
| --- | --- | --- |
| Base | Exact 15-player valid squad | 15/15 roster and slots, but missed VC; invalid |
| v3 | Exact 15-player valid squad | Exact valid roster/C/VC/formation; one hidden chip hallucinated |
| v4 | Exact 15-player valid squad | Duplicate role-local starter slots; only 9 rows survive strict parsing; invalid |

The v4 desktop failure is a schema-behaviour regression, not an OCR failure: all visible player
names were read, but starter order restarted at one for each position row. This validates the
architecture decision to keep entity resolution, slot uniqueness, formation and squad legality in
deterministic code and to require user confirmation.

## Selection and next experiment

- Do not deploy v4.
- Use v3 only for guarded screenshot extraction; keep deterministic validation and confirmation.
- For chat, retain the base model plus typed policy/routing until an adapter improves route, schema,
  safety and multilingual scores together.
- Before v5, expand the locked suite and add semantic grading. Build corrections from exact v4
  failures, especially no-tool glossary answers, stale/injection refusals, multilingual routes and
  global starter-slot numbering. Reduce the correction learning rate or use fewer steps if replay
  protections still fail.
- A 9B challenger is only worthwhile after the evaluation/data contract is stronger; current
  failures are mostly supervision and routing-policy failures, not demonstrated capacity limits.

Artifacts: training manifest at
`llm/outputs/qwen35-4b-fpl-lora-v4/training_manifest.json`, text evaluation at
`data/llm/evaluations/qwen35-4b-fpl-lora-v4-text-v3.json`, and real-image extractions under
`data/llm/evaluations/qwen35-4b-fpl-lora-v4-{mobile,desktop}.json`.
