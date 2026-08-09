# FPLAgent multimodal LLM foundation

Status: implemented foundation, v3 broad corpus, v4 correction run and locked three-way
base/v3/v4 evaluation, 4 August 2026. No adapter is promoted as the autonomous chatbot default;
v3 is the current guarded screenshot-extraction candidate.

## Decision

Use **Qwen3.5-4B** as the first promoted-model candidate and keep
**Qwen3.5-9B** as the quality challenger. Do not reduce the upload feature to OCR-only.
Qwen3.5 is a unified vision-language model, so the same adapter can support normal FPL chat,
tool use and team-image understanding. The 4B model is Apache-2.0 licensed, has native visual
input and tool-use support, and its official model card reports a 262k native context window.
See the [Qwen3.5-4B model card](https://huggingface.co/Qwen/Qwen3.5-4B).

The alternatives remain useful controls, not the starting point:

| Candidate | Strength | Why it is not the default |
| --- | --- | --- |
| Qwen3.5-4B | Multimodal, tool-oriented, Apache-2.0, strong measured screenshot result, fast BF16 LoRA | Selected |
| Qwen3.5-9B | More capacity and still fits the 5090 | Official Unsloth estimate is about 22 GB for BF16 LoRA, leaving less headroom; run only if 4B misses promotion gates |
| Ministral 3 3B | Apache-2.0, vision-capable, small edge model | Attractive latency challenger, but the Qwen path has the stronger current tool/training integration and is already validated on the supplied image |
| Gemma 3 4B | Capable multimodal model | Gated download and the Gemma usage licence add friction compared with Apache-2.0 Qwen |
| Llama 3.2 11B Vision | Established ecosystem | Larger, older and under the Llama licence; poorer fit for rapid 32 GB iteration |

### Qwen3.6 and the absence of Qwen3.7

As checked on 4 August 2026, there is no official Qwen3.7 release on Hugging Face. The current
official successor collection is [Qwen3.6](https://huggingface.co/collections/Qwen/qwen36), and it
contains only Qwen3.6-27B dense and Qwen3.6-35B-A3B plus their FP8 variants. Both are multimodal,
but neither is a small-model replacement for this project. The
[Qwen3.6-27B model card](https://huggingface.co/Qwen/Qwen3.6-27B) identifies a 28B-parameter BF16
checkpoint. A 27B QLoRA may nominally fit a 32 GB card with aggressive settings, but vision
training, activations and a useful sequence length leave poor headroom and make a few-hour run
unrealistic. It is a useful quantized teacher/critic, not the local SFT target.

The decision therefore remains Qwen3.5-4B first and Qwen3.5-9B only as a challenger. Re-run the
model search immediately before the full corpus run: if Qwen releases a 3.6/3.7 model around
4B-9B with supported multimodal BF16 LoRA, benchmark it against exactly the same locked suite
before committing the full GPU run.

The current [Unsloth Qwen3.5 guide](https://unsloth.ai/docs/models/qwen3.5/fine-tune)
explicitly supports vision and text fine-tuning, estimates roughly 10 GB for 4B BF16 LoRA and
discourages QLoRA for this family. That is why the checked-in recipe uses BF16 LoRA, not 4-bit
training. The measured peak here was 10,424,942,592 bytes (9.71 GiB).

For retrieval, start with
[Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B): it is
Apache-2.0, instruction-aware, supports 32k inputs and emits up to 1,024-dimensional vectors.
Dense retrieval must be combined with lexical retrieval because FPL player names, abbreviations
and gameweek labels benefit from exact matching.

## What belongs in each layer

The adapter is for stable behaviour, not a frozen copy of this week's game state.

| Layer | Put here | Do not put here |
| --- | --- | --- |
| SFT adapter | FPL vocabulary and tone, clarification habits, tool selection, evidence discipline, screenshot schema, explaining decision receipts | Current prices, injuries, ownership, fixtures, deadlines or transient forecasts |
| Versioned RAG | Rules, glossary details, owned research, methodology, historical evidence, attributable news with observation time | Computation that already has a structured authoritative source |
| Structured tools | Manager state, official player snapshot, fixtures, forecasts, captain comparison, transfer evaluation, squad optimisation, decision receipts | Free-form prose copied into prompts without provenance |
| Deterministic code | Entity resolution, legal-squad checks, budget/club/formation constraints, date normalization, confirmation state | Natural-language judgement or invented repair |

The numeric decision engine stays authoritative. The LLM chooses and explains tool calls; it does
not replace the optimizer or silently recalculate its answer.

## Runtime architecture

```text
question or image upload
          |
          v
Qwen3.5-4B + FPL LoRA  <---- versioned hybrid retrieval
          |
          +---- typed tool calls ----> live FPL state + decision engine
          |
          +---- image extraction ----> OCR cross-check (optional evidence)
                                       |
                                       v
                              current-player resolver
                                       |
                                       v
                              deterministic FPL validator
                                       |
                                       v
                              user review and confirmation
```

For images, the VLM is primary and OCR is a second source of evidence. OCR remains valuable for
cross-checking small labels and providing a cheap fallback, but it cannot reliably infer pitch
semantics, captain badges, bench ordering or chip state by itself. Neither VLM nor OCR may assign
official player IDs. The resolver matches visible text against the current-season catalog and
leaves close or low-confidence matches unresolved. The user must confirm the resulting team.

## Supplied screenshot baselines

The locked `fpl-team-001` case records the exact image checksum and expected 15-player squad.
Running unfine-tuned Qwen3.5-4B on the real 1,042 × 2,048 JPEG produced valid JSON and achieved:

- 15/15 visible player identities resolved;
- 15/15 starter-versus-bench roles;
- correct captain, vice-captain and bench sequence;
- 4/4 chip states and the correct gameweek;
- no invented player IDs and no unresolved names.

With the final extraction prompt, the base model also emits the correct global starter/role-local
bench slots and 5-3-2 formation, so the mobile proposal validates. The visible historical deadline
is retained as extracted evidence but not silently trusted as current state. This is a good result:
visual reading is already strong and the remaining problems are schema/normalization behaviours
suited to targeted SFT and post-processing.

The generated baseline and score are local rebuildable artifacts under
`data/llm/generated/fpl-team-001-base-*.json`.

The locked desktop case is 988 × 919 and intentionally hides the gameweek, deadline and chip
panel. Base Qwen3.5-4B resolves all 15 identities, roles and exact slots, the captain, bench order,
formation and absent metadata/chip fields. It misses the small vice-captain badge, so validation
correctly rejects the proposal. V3 finds that badge and reconstructs a valid squad, although it
hallucinates one hidden chip value. V4 reads every name but restarts starter order for each position
row, creating duplicate slots and an invalid proposal. This directly defines two curriculum
families: small C/VC/status badges and global slot numbering across visual rows.

Neither supplied image enters training. They remain locked, checksum-pinned evaluation cases so
the synthetic image generator cannot leak their exact squad or layout into SFT.

## Training corpus

The corrected deterministic v3 corpus contains **12,000 conversations**: 10,800 text/tool rows
and the 1,200-image curriculum. It is split 9,600/1,200/1,200 by scenario group and squad, so
paraphrases and alternate views do not leak across train, validation and test. The small original
60-row seed remains only as a format and throughput smoke set. V3 aligns manager IDs to the
application's integer contract without changing the family distribution.

| Family | Rows | Construction |
| --- | ---: | --- |
| Natural FPL dialogue | 2,600 | Stable terminology, strategy explanation, beginner/expert register and multi-turn follow-ups |
| Tool routing and grounded answers | 4,000 | Typed requests, synthetic point-in-time results and faithful summaries |
| Decision explanations | 1,800 | Engine receipts expressed as recommendations, trade-offs, uncertainty and counterfactuals |
| Ambiguity, staleness and safety | 1,200 | Missing state/horizon, stale news, prompt injection, unsupported certainty and confirmation discipline |
| Multilingual replay | 600 | 100 each in Spanish, French, German, Portuguese, Simplified Chinese and Arabic |
| Format and repair | 600 | Strict JSON, incomplete uploads, invalid bench orders and bounded-horizon repairs |
| Multimodal team import | 1,200 | Owned rendered teams, distinct held-out templates, damaged captures and incomplete uploads |

There are 6,720 typed-tool rows. Every argument object is validated against the same runtime
contract used by the application. The generator also enforces grounded numeric/value mentions,
scenario-level split isolation, exact benchmark exclusion and near-contamination screening (the
maximum observed similarity is 0.7811 against a 0.94 failure threshold). It produced 9,427 unique
assistant targets; the most repeated target occurs ten times. Community data contributes only
aggregate intent-category counts and no source text is copied into an answer.

English remains the main SFT language. Reserve roughly 5–10% for multilingual replay and parallel
FPL/tool examples rather than translating the entire corpus. The assistant mirrors the user's
language while player IDs, schemas and tool names remain language-neutral. Spanish, French,
German, Portuguese, Simplified Chinese and Arabic are now represented in the locked text suite;
expand by observed usage later. Promotion requires no material regression from base Qwen on this
multilingual slice.

### Standalone screenshot renderer

The app does not yet render arbitrary squads, so a standalone deterministic SVG/CSS dataset
renderer is implemented rather than waiting for the upload UI. It samples only legal squads from
the current catalog, adds point-in-time fixture labels, rasterizes through ImageMagick and writes
an image plus exact private truth. Its manifest includes labels, player IDs, roles, C/VC, bench
order, chips, viewport, template version, source snapshot and random seed.

The original contract slice contains eight squads and 16 pitch images, covers all eight legal
formations, and splits 12/2/2 by train/validation/test at squad level. The completed v2 curriculum
contains **240 unique squads and 1,200 images**, split 960/120/120. Every legal formation has 150
images. Train and validation share four in-distribution families (`canvas`, `compact`, `roster`,
`ledger`); test uses only two visually distinct held-out families (`broadcast`, `paper`). A squad
signature belongs to exactly one split, so no alternative view of the same team leaks across the
boundary. Repeating the build with seed `20260811` and the same database snapshot reproduces the
checksums.

The v2 renderer supports mobile and desktop pitch and list views with:

- every legal formation, bench ordering and chip state, plus deliberately hidden metadata;
- long, hyphenated, accented and truncated names, fixture suffixes and promoted/relegated clubs;
- C/VC badges at varied scale and contrast;
- edge crops, JPEG round trips, downscale/upscale damage, blur, and deterministic screen-photo
  perspective, lighting and noise;
- 60 incomplete uploads with one genuinely obscured bench slot for the resolver, validator and
  confirmation path.

Each incomplete row has 14 visible targets, an explicit unresolved region and an expected-invalid
proposal. The generator separately retains the complete legal squad as private audit truth; it is
never emitted as the assistant target. An independent audit verified every image/SVG/truth hash,
PNG dimension, full and visible validation result, split assignment and SFT row. The complete
artifact is about 381 MB under `data/llm/generated/screenshot_corpus_v2`.

The 1,200-image target is now met. Grow it only from measured failure clusters, and preserve the
template and squad boundaries when doing so. Use generic or rights-cleared kit assets; the layout
needs FPL semantics, not copied branding. Every image row carries source, rights, synthetic status,
generator version and split metadata. Current facts are tool results, not target knowledge to
memorize.

Base Qwen3.5-4B was run on the generated validation squad in both viewports. The mobile image
produced 15 player rows, resolved 13/15, read all four chip states and the bench order, but guessed
4-3-3 for the true 5-2-3 and missed the vice-captain. The desktop image emitted only the 11
starters, resolved 8/15, and also guessed 4-3-3. Deterministic validation rejected both. This
confirms the generated curriculum is testing formation-from-layout, role-slot assignment and
badge association rather than merely clean OCR.

### Web and official-data acquisition

The project owner has confirmed private, non-commercial research scope and asked to continue the
existing official FPL extraction. The LLM pipeline therefore permits cached, rate-limited official
FPL research extracts for structured tools, evaluation and versioned RAG. It retains URL,
observation time, response checksum, season and extraction code version and does not redistribute
raw dumps. Structured facts can be transformed into original SFT scenarios; official prose is not
copied into the adapter.

For the wider web, discover the questions, terminology and reasoning patterns people actually use,
but do not bulk-copy community posts or articles as model answers. Reddit in particular is intent
discovery only unless individual rightsholders grant permission: its current
[Data API Terms](https://redditinc.com/policies/data-api-terms) explicitly say the API licence does
not include AI-training rights to user content. Other web sources default to quarantine until
their licence, terms, author, upstream lineage and permitted uses are recorded. A checked-in
`source_registry_v1.json` makes those decisions executable instead of relying on memory.

## Retrieval plan

Index heading-aware chunks with these required fields: `chunk_id`, source URI/path, document and
chunk checksums, title/heading, rights, season, `valid_from`, `valid_to`, `observed_at`, temporal
class and namespace. Retrieval is filtered before ranking:

1. select namespace and applicable season/time;
2. retrieve lexical and dense candidates;
3. fuse ranks and optionally rerank the small shortlist;
4. pass compact excerpts with source and observation time;
5. require the answer to cite claims and expose uncertainty when evidence conflicts.

Initial namespaces are `rules`, `glossary`, `methodology`, `historical_evidence`, `news` and
`decision_receipts`. Live structured state never goes through the vector index. Retrieved content
and image text are untrusted evidence, not instructions.

## Measured training time on this RTX 5090

The isolated stack successfully loaded Qwen3.5-4B and completed response-only BF16 LoRA training.
A warmed 10-step calibration processed an estimated 24,291 short-sequence tokens in 14.4485
seconds. V3 trained 9,600 examples for one epoch and 600 optimizer steps in **1,314.46 seconds (21
minutes 54 seconds)** at 15.01 GiB peak reserved VRAM. V4 trained its 13,600-row correction/replay
mixture for 850 steps in **1,896.66 seconds (31 minutes 37 seconds)** at 20.71 GiB peak. Both are
comfortably inside the requested few-hour local window.

The full rendered train set has 9,600 rows and about 4.03 million text tokens before visual image
tokens. Its actual sequence distribution is p50 349, p95 842, p99 886 and maximum 928 tokens, so
the 2,048-token training ceiling truncates no example. The four-hour callback remains as a safety
limit. Qwen3.5-9B should be treated as a separate challenger likely to take materially longer;
benchmark it rather than assuming it fits the same window.

An earlier full `v2` run was rejected after audit because the data collator trained on the entire
rendered conversation instead of masking system, user and tool-result tokens. `v3` corrects this
with response-only masking; the setting is explicit in both config and training manifest.

## Candidate evaluation and selection

The authoritative 37-case suite uses identical integer-ID schemas, fixed tool fixtures and Qwen's
`<|im_end|>` turn stop. Earlier evaluations that stopped on `<|endoftext|>` are not comparable.

| Measure | Base 4B | v3 | v4 final |
| --- | ---: | ---: | ---: |
| Exact tool route | 16/37 | **21/37** | 14/37 |
| Valid tool arguments | **37/37** | 36/37 | 34/37 |
| Strict lexical response contract | **10/37** | 7/37 | 9/37 |
| Clean turn boundary | 37/37 | 37/37 | 37/37 |
| All four checks | 6/37 | 6/37 | **8/37** |

V4's two extra complete cases do not offset its routing/schema regressions. Checkpoint 510 was
worse again at 13 routes, 33 valid arguments and seven complete cases. Neither adapter passes the
chat promotion gates.

On the two supplied screenshots, all three candidates are exact and valid on mobile. Desktop
separates them: base misses the vice-captain, v3 reconstructs the full valid team but hallucinates
one hidden chip, and v4 creates duplicate starter slots. V3 is therefore the best current guarded
vision candidate. The complete records are in [`fpl-llm-training-v3.md`](fpl-llm-training-v3.md)
and [`fpl-llm-training-v4.md`](fpl-llm-training-v4.md).

## Promotion gates

Compare base 4B, adapted 4B and—only if needed—base/adapted 9B with identical tools and retrieval.
No adapter is promoted from training loss alone. The initial gates are:

- 100% valid typed tool arguments on the locked cases;
- 100% numeric faithfulness to returned tool values;
- zero invented player IDs or current facts;
- at least 95% expected tool-route exact match;
- at least 99% player identity accuracy and 98% exact reconstructed teams on a larger screenshot set;
- deterministic rejection of every illegal or unresolved import;
- at least 98% supported-claim/citation precision on retrieval cases;
- no regression on prompt-injection and stale-data cases;
- human FPL-language review preferred to the base model without becoming overconfident.

The current locked text suite contains 37 cases across eleven categories. It is a foundation, not a
statistically sufficient final evaluation; expand it before model promotion.

## Execution sequence

1. Expand the locked suite, especially multilingual, prompt-injection, ambiguity, staleness and
   global screenshot-slot cases; add semantic and FPL-human grading beside lexical checks.
2. Build v5 only from reviewed v4 failure clusters while retaining broad replay. Test lower learning
   rates and earlier checkpoints to reduce route/schema forgetting.
3. Keep v3 behind deterministic screenshot validation and explicit user confirmation; never trust
   hidden metadata or model-assigned player IDs.
4. Keep base plus typed policy/routing for chat until one adapter improves route, schema, safety and
   multilingual behaviour together.
5. Train the 9B challenger only if the improved benchmark demonstrates a capacity limit rather than
   a data/contract problem.
