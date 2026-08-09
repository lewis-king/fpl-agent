# FPLAgent local multimodal fine-tuning

> **Workstream parked — 7 August 2026.** Do not run training, adapter inference, corpus
> generation, evaluation or promotion unless Lewis explicitly reopens this workstream. No v5-v8
> text adapter was promoted; the prepared v9 corpus was not trained. These commands and artifacts
> are retained only as a resumable research record. See the
> [project status](../docs/project-status.md) for the active points-first objective and the
> [V5-V9 handoff](../reports/fpl-llm-v5-experiment.md) for the exact stopping point.

For the project-level explanation of how the Qwen base model, FPL LoRA adapter, Unsloth, PEFT,
grounded tools and multimodal upload pipeline fit together, see
[the canonical FPL LLM architecture guide](../docs/fpl-llm-architecture.md).

This directory isolates the fast-moving Qwen3.5/Unsloth environment from the stable decision
engine. The base model remains multimodal. The first adapter trains language attention and MLP
layers while freezing the vision encoder; mixed screenshot examples can still teach the language
side how to interpret the pretrained visual representation.

The install recipe follows the current official Unsloth Qwen3.5-4B vision notebook. Recheck it
before a later rebuild because this stack changes quickly. `torchao` is deliberately pinned to
0.16.0: newer 0.18 builds require a newer PyTorch than the notebook's Qwen3.5-compatible 2.8 pin.

## Prepare the foundation data

```bash
uv run fplagent-llm validate-benchmarks --image-root /home/lewis/Downloads
uv run fplagent-llm build-data
uv run fplagent-llm build-conversation-corpus
```

`fpl_sft_seed_v1.jsonl` is intentionally too small for a promoted model. The trainer refuses it
unless `--allow-seed-data` is supplied. It exists to validate formatting and measure throughput
before producing the full corpus.

The corrected deterministic v3 corpus is built under `data/llm/generated/fpl_corpus_v3`. It contains
12,000 rows: 10,800 text/tool conversations and 1,200 synthetic screenshot conversations. The
combined split is 9,600 train, 1,200 validation and 1,200 test rows, grouped by scenario and squad
so paraphrases or alternate image views cannot cross splits. Version 3 aligns manager IDs with the
application's integer contract; its train hash is
`3ad04d5e35052f771f8207a81ca182b619d56036e8094d156b0ee196427949d2`. The text families are:

| Family | Rows |
| --- | ---: |
| FPL language and strategy | 2,600 |
| Typed tool routing and grounded answers | 4,000 |
| Decision-receipt explanations | 1,800 |
| Ambiguity, staleness and safety | 1,200 |
| Multilingual FPL/tool replay | 600 |
| Strict-format and repair cases | 600 |

All 6,720 tool-bearing rows are checked against the runtime schemas. The build also checks exact
and near benchmark contamination, grounded-value faithfulness, duplicate target concentration,
split isolation and full row validity. Community material contributes aggregate intent counts
only; no community text is copied into targets. Current player, fixture and forecast values occur
inside synthetic tool results rather than as unsupported model knowledge.

## Install the isolated training environment

```bash
bash llm/install_qwen35.sh
```

The script creates `llm/.venv`; it does not alter the repository `.venv`.

## Run the screenshot baseline

```bash
llm/.venv/bin/python llm/evaluate_screenshot.py \
  --image /home/lewis/Downloads/fpl-team.jpeg \
  --output data/llm/generated/fpl-team-001-base-extraction.json
```

This is the VLM-only baseline. Production import will additionally use OCR, current-player entity
resolution, deterministic squad validation and explicit user confirmation.

## Generate synthetic multimodal examples

The standalone renderer samples legal squads from the current catalog, attaches the selected
event's fixture labels, renders original generic kits/layouts, and writes exact private truth.
The default eight squads cover every legal formation once and create both mobile and desktop
images:

```bash
uv run fplagent-llm render-screenshots \
  --squads 8 \
  --seed 20260804
```

This produces the 16-image contract smoke set under
`data/llm/generated/screenshot_render_v1`: 12 train, two validation and two test rows. Both
viewports for a squad always remain in the same split. The manifest pins
the source snapshot, squad signature, viewport, visibility flags, damage transform and checksums
for the image, SVG and truth. Repeating the command against the same database snapshot produces
the same hashes.

Validate that the multimodal rows load in the isolated trainer without beginning a run:

```bash
llm/.venv/bin/python llm/train_qwen35.py \
  --train-data data/llm/generated/screenshot_render_v1/sft_train.jsonl \
  --image-root data/llm/generated/screenshot_render_v1 \
  --allow-seed-data \
  --dry-run
```

Build the full screenshot curriculum with:

```bash
uv run fplagent-llm render-screenshot-corpus
```

The deterministic v2 build contains 240 unique legal squads and five views of each squad: 1,200
images occupying about 381 MB. It writes 960 train, 120 validation and 120 test rows under
`data/llm/generated/screenshot_corpus_v2`. Train and validation use the `canvas`, `compact`,
`roster` and `ledger` template families. Test uses only the held-out `broadcast` and `paper`
families, while squad signatures never cross splits. Every legal formation has 150 examples.

The corpus mixes pitch and list views, mobile and desktop dimensions, metadata/chip visibility,
name truncation, clean and damaged captures, and 60 partial uploads. A partial row omits the
obscured player from the visible extraction and is expected to fail deterministic validation;
its private 15-player truth is retained only for generator auditing. Rebuild with the same seed
and source snapshot to reproduce its checksums.

Preflight the full image training split without starting a model run:

```bash
llm/.venv/bin/python llm/train_qwen35.py \
  --train-data data/llm/generated/screenshot_corpus_v2/sft_train.jsonl \
  --image-root data/llm/generated/screenshot_corpus_v2 \
  --allow-seed-data \
  --dry-run
```

The image split alone has 960 train rows, so `--allow-seed-data` is appropriate for this isolated
preflight. Do not use it for promotion training: first merge these rows with the reviewed
language, tool-routing and decision-explanation corpus so screenshots do not dominate the
adapter.

Score an extraction against the locked image truth:

```bash
uv run fplagent-llm score-screenshot \
  --extraction data/llm/generated/fpl-team-001-base-extraction.json \
  --case-id fpl-team-001
```

With the current extraction prompt, base Qwen3.5-4B resolves the supplied mobile screenshot exactly:
15/15 identities, roles and slots, captain/vice-captain, bench order, chip states and 5-3-2. On the
desktop image it again resolves all 15 players and slots, but misses the small vice-captain badge;
deterministic validation therefore rejects that proposal. Formation is derived from the 11 parsed
starter positions and the raw VLM label is still reported separately, so a redundant label error
cannot invalidate an otherwise exact roster.

An unfine-tuned 4B baseline was also run on a generated 5-2-3 squad. On mobile it read all 15 rows,
resolved 13, got every chip and the bench order, but guessed 4-3-3 and missed the vice-captain. On
desktop it emitted only the 11 starters, resolved eight, and again guessed 4-3-3. Both were
correctly rejected. Score a generated baseline against its private truth with:

```bash
uv run fplagent-llm score-synthetic-screenshot \
  --extraction data/llm/generated/screenshot_render_v1/baseline/synthetic-squad-0005-mobile-base.json \
  --truth data/llm/generated/screenshot_render_v1/truth/synthetic-squad-0005-mobile.json
```

## Check data-source decisions

```bash
uv run fplagent-llm source-policy
```

The source registry permits the project's existing official FPL extraction for private research,
runtime tools and RAG, while keeping copied official prose out of SFT. Unknown web sources default
to denied until reviewed. Community content can guide intent coverage without becoming copied
training dialogue.

## Smoke-test training and measure throughput

```bash
llm/.venv/bin/python llm/train_qwen35.py \
  --train-data data/llm/generated/fpl_sft_seed_v1.jsonl \
  --allow-seed-data \
  --max-steps 20 \
  --max-wall-minutes 30
```

Use the measured token/second rate to project the full run:

```bash
uv run fplagent-llm estimate-training \
  --planned-tokens 8000000 \
  --calibration-tokens 200000 \
  --calibration-seconds 300
```

The candidate run uses one epoch and a four-hour wall-clock callback. It writes an adapter and a
manifest containing the exact dataset/config hashes, GPU, versions, duration and peak VRAM.

The warmed 10-step RTX 5090 calibration took 14.4485 seconds at 9.71 GiB peak reserved VRAM.
The completed 9,600-row v3 run took 1,314.46 seconds (21 minutes 54 seconds) and peaked at 15.01
GiB. The larger 13,600-row v4 correction/replay run took 1,896.66 seconds (31 minutes 37 seconds)
and peaked at 20.71 GiB. Evaluation and image inference are additional work, but both actual local
fine-tunes are comfortably inside the requested few-hour window.

## Train the response-only v3 candidate

`v2` was a completed engineering run, but its collator trained the whole rendered transcript,
including system, user and tool-result tokens. It is retained only as a diagnostic artifact. The
corrected `v3` configuration masks every token except assistant responses and tool calls; use it
for reproducibility and as the starting point for the next experiment.

First run the same trainer preflight used by the real job:

```bash
llm/.venv/bin/python llm/train_qwen35.py \
  --config llm/configs/qwen35_4b_fpl_v3_lora.json \
  --train-data data/llm/generated/fpl_corpus_v3/combined_train.jsonl \
  --image-root data/llm/generated/fpl_corpus_v3 \
  --dry-run
```

Then remove `--dry-run`:

```bash
llm/.venv/bin/python llm/train_qwen35.py \
  --config llm/configs/qwen35_4b_fpl_v3_lora.json \
  --train-data data/llm/generated/fpl_corpus_v3/combined_train.jsonl \
  --image-root data/llm/generated/fpl_corpus_v3
```

The checked-in configuration runs one BF16 LoRA epoch with batch size 2, gradient accumulation
8, a 2,048-token ceiling and a four-hour hard stop. The actual rendered train distribution is
p50 349, p95 842, p99 886 and maximum 928 tokens; no row is truncated at 2,048. The adapter is
written to `llm/outputs/qwen35-4b-fpl-lora-v3/adapter` together with hashes and environment
metadata. The measured final training loss was 0.12209; loss is recorded for reproducibility, not
used as a promotion signal.

## Evaluate base and adapter

Run the locked text suite with identical schemas and fixed synthetic tool fixtures:

```bash
llm/.venv/bin/python llm/evaluate_text.py \
  --output data/llm/evaluations/qwen35-4b-base-text-v3.json

llm/.venv/bin/python llm/evaluate_text.py \
  --adapter llm/outputs/qwen35-4b-fpl-lora-v3/adapter \
  --output data/llm/evaluations/qwen35-4b-fpl-lora-v3-text-v3.json
```

The authoritative evaluator stops on Qwen's chat end token, `<|im_end|>`, and uses the same
integer manager-ID schema as runtime. Earlier `*-text.json` files used the base model's
`<|endoftext|>` token and are retained only as diagnostic history. The corrected 37-case result
is mixed, so `v3` is **not promoted as the chatbot default**:

| Measure | Base 4B | v3 adapter |
| --- | ---: | ---: |
| Exact tool route | 16/37 | 21/37 |
| Valid tool arguments | 37/37 | 36/37 |
| Strict lexical response contract | 10/37 | 7/37 |
| Clean raw turn boundary | 37/37 | 37/37 |
| All four checks | 6/37 | 6/37 |

The response score is deliberately literal and can reject a semantically valid negation, so it is
a conservative regression signal rather than a standalone quality score. The earlier apparent
turn-boundary regression was an evaluator stop-token bug, not an adapter regression.

With the corrected image prompt, `v3` produces a fully valid squad from both supplied screenshots.
Mobile is exact on every scored field. Desktop is exact on the 15-player roster, slots, formation,
C/VC and bench order, but hallucinates one hidden chip value; the importer still requires user
confirmation and treats hidden metadata as untrusted.

## Train and assess the v4 correction candidate

Build the 13,600-row mixture and train from the clean base model:

```bash
uv run fplagent-llm build-correction-corpus

llm/.venv/bin/python llm/train_qwen35.py \
  --config llm/configs/qwen35_4b_fpl_v4_lora.json \
  --train-data data/llm/generated/fpl_correction_v4/combined_train.jsonl \
  --image-root data/llm/generated/fpl_correction_v4
```

The mixture contains 9,600 broad replay rows and 4,000 targeted corrections: 1,200 FPL language,
1,000 tool-route, 800 decision-route, 400 safety, 200 multilingual and 400 formation-image rows.
It is response-only BF16 LoRA from the clean base, not an adapter stacked on v3. The final result:

| Measure | Base 4B | v3 | v4 final |
| --- | ---: | ---: | ---: |
| Exact tool route | 16/37 | **21/37** | 14/37 |
| Valid tool arguments | **37/37** | 36/37 | 34/37 |
| Strict lexical response contract | **10/37** | 7/37 | 9/37 |
| Clean turn boundary | 37/37 | 37/37 | 37/37 |
| All four checks | 6/37 | 6/37 | **8/37** |

Checkpoint 510 scored 13/37 routes, 33/37 valid arguments and 7/37 complete cases, so it is not a
better fallback. V4 is not promoted: its extra two complete text cases do not compensate for the
route/schema regression, and its desktop screenshot used duplicate role-local starter slots,
making the squad invalid. Keep v3 as the best current vision adapter and keep base/v3 routing under
an application policy layer until the benchmark is expanded and a later adapter passes every gate.

## Application-conversation experiments v5-v8

The later application benchmark contains 58 held-out prompts: 50 ordinary/no-tool conversations
and eight current-team routes using the four tools exposed by the web app. Base Qwen under the same
system prompt scored 15 complete cases, 50/50 no-tool routes and 3/8 grounded routes.

- V5 trained on 24,000 rows but failed because text rows did not contain Qwen's runtime tool
  preamble. It learned that seeing tools was itself a reason to call one.
- V6 aligned the training and inference templates, improving routing to 49/50 and 7/8, but its
  repeated synthetic endings damaged prose; it scored 23/58 complete cases.
- V7 used a curated 5,476-row quality corpus and routed 8/8 grounded cases, but one low-rate epoch
  remained under-trained and scored 19/58 complete cases.
- V8 extended the quality run. Checkpoints 500 and 750 kept all direct prompts tool-free but routed
  only 2/8 and 3/8 current decisions, scoring 16/58 and 17/58 complete cases.

None passed the preregistered 40/58 promotion threshold, so none is the text-chat default. The app
continues to use base Qwen plus the application policy, typed tools and deterministic guards; V3 is
retained only for screenshot extraction. Reproduce the V7 corpus with:

```bash
uv run fplagent-llm build-quality-corpus
```

The complete dataset hashes, training recipes, failure analysis and evaluation table are in
`reports/fpl-llm-v5-experiment.md`. These negative results are intentional project artifacts rather
than candidates to silently deploy.

## Run the local grounded chatbot

The first application-policy runtime is now implemented. It runs Qwen behind a bounded tool loop
instead of asking the model to remember current FPL facts or calculate decisions itself. The model
chooses when to call a tool and explains the result; the application validates every call against
the training-time JSON schemas and the numeric engine remains authoritative.

Inspect the two enabled read-only tools without loading a model:

```bash
uv run fplagent-llm runtime-tools \
  --manager-id 1 \
  --event 1 \
  --risk-policy robust \
  --as-of 2026-08-06T09:00:00+01:00
```

Start a single local Qwen turn on the RTX 5090:

```bash
llm/.venv/bin/python llm/chat_qwen35.py \
  --manager-id 1 \
  --event 1 \
  --prompt "Who should I captain for GW1? Use a robust policy."
```

Omit `--prompt` for an interactive terminal session. The unfine-tuned base model is the default
because neither language adapter passed the promotion gate. Add
`--adapter llm/outputs/qwen35-4b-fpl-lora-v3/adapter` only when deliberately testing the current
best screenshot adapter.

Runtime v1 currently exposes:

- `get_manager_state`: adapts the versioned local GW1 decision artifact into a typed manager-state
  response, including provenance, unavailable fields and staleness markers.
- `compare_captains`: restricts candidates to the stored starting XI and returns a versioned
  forecast comparison, captain/vice pair, decision receipt, evidence status and refresh caveat.

Manager ID 1 is a local synthesized research snapshot rather than an authenticated live FPL
account. It is therefore marked unconfirmed, requires a live refresh, and does not claim values for
free transfers or chips. The current captain service supports GW1 and the `expected_points` and
`robust` policies. It rejects mini-league mode until rank, rival and objective context exist.

The orchestration guard turns a failed captain tool into an explicit no-recommendation response,
adds a refresh warning when the model omits one, enforces a finite tool loop, and checks Qwen's turn
boundary. Events are written to `data/llm/runtime/chat_events.jsonl`; user and response content are
hashed rather than stored unless `--log-content` is explicitly supplied. A live base-model smoke
test called manager state followed by captain comparison, returned receipt
`captain-v1-f5f10bd0000db287`, and completed without a safety failure.

## Non-negotiable promotion boundary

- The adapter is not promoted from training loss.
- It must beat base Qwen3.5 plus identical tools/RAG on the locked FPL benchmarks.
- Screenshot output is provisional until exact player IDs resolve and squad validation passes.
- The numeric engine remains authoritative for captaincy, transfers and optimisation.

See [the full architecture and execution plan](../reports/fpl-llm-foundation.md).
