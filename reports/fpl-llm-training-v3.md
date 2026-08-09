# Qwen3.5-4B FPL candidate v3: training and evaluation

Date: 4 August 2026  
Status: trained and evaluated; **not promoted**

## Outcome

The first correctly masked, response-only FPL adapter is reproducible and fits the local hardware
comfortably. It improved exact tool-route selection but did not beat the base model across the
complete locked text contract. Its screenshot extraction is useful behind deterministic validation
and is currently stronger than the later v4 adapter on the two real-image cases. Keep it as the
current vision candidate, but do not make it the unguarded chatbot default.

## Reproducible training record

| Item | Result |
| --- | --- |
| Base | `unsloth/Qwen3.5-4B` |
| Training data | 9,600 grouped train conversations from the 12,000-row v2 corpus |
| Objective | Assistant responses and tool calls only |
| Method | BF16 LoRA, rank 16, alpha 16; vision encoder frozen |
| Effective batch | 16 (batch 2, gradient accumulation 8) |
| Epochs / optimizer steps | 1 / 600 |
| Learning rate | 0.00005, linear schedule |
| Wall time | 1,314.46 seconds (21 minutes 54 seconds) |
| Peak reserved VRAM | 16,118,710,272 bytes (15.01 GiB) |
| Final train loss | 0.122094 |
| Adapter size | 129,934,448 bytes |

The manifest pins config hash
`1836ab636029d00ec7c24dcc4b2b3923a6afaa931667595189bb59ebc2888ac4` and train-data hash
`cb2fbbc98f6369f8ca6e949ef75b79d190eb871c6ea55515904fafd70820283d`.

An earlier `v2` run trained on the whole rendered transcript because response masking was not
enabled. That run is rejected and must not be compared as a model candidate. The trainer now
defaults to response-only masking and records the setting in its manifest.

## Locked text benchmark

All models received the same 37 prompts, tool schemas and fixed synthetic tool results. The suite
measures routing and format behaviour; it does not claim that its fixture values are live FPL
facts.

| Measure | Base 4B | v3 adapter | Change |
| --- | ---: | ---: | ---: |
| Exact tool route | 16/37 (43.2%) | 21/37 (56.8%) | +5 |
| Valid tool arguments | 37/37 (100%) | 36/37 (97.3%) | -1 |
| Strict lexical response contract | 10/37 (27.0%) | 7/37 (18.9%) | -3 |
| Clean turn boundary | 37/37 (100%) | 37/37 (100%) | 0 |
| All four checks | 6/37 (16.2%) | 6/37 (16.2%) | 0 |

Useful gains appeared in multi-step routing and grounding. Important failures included unnecessary
retrieval for stable FPL vocabulary, one invalid argument object and weak definitions such as
"nailed". The phrase checker is intentionally strict and sometimes penalizes a correct negation.

These are the corrected evaluator-v3 results. Earlier numbers in the first report used the model
config's `<|endoftext|>` ID rather than Qwen's `<|im_end|>` chat-turn token and also disagreed with
runtime about whether manager IDs were strings or integers. That made the old boundary and schema
comparison invalid; the files remain only as diagnostic artifacts.

## Supplied screenshot benchmark

The two user-supplied screenshots were checksum-pinned evaluation cases and were never included in
training.

| Measure | Mobile | Desktop |
| --- | ---: | ---: |
| Parsed JSON | yes | yes |
| Player identity / role / slot | 15/15 | 15/15 |
| Captain / vice-captain | both correct | both correct |
| Bench order | correct | correct |
| Visible/hidden chips | 4/4 correct | 3/4 correct |
| Formation | correct: 5-3-2 | correct: 5-3-2 |
| Deterministic team validation | valid | valid |

The corrected prompt explicitly derives formation by counting starter positions. The importer also
recomputes that redundant field deterministically while retaining the raw VLM label as an audit
metric. Compared with base Qwen3.5-4B, v3 detects the small desktop vice-captain badge and therefore
produces a valid roster; it does hallucinate one chip value on the desktop image where the chip
panel is hidden. Production import must retain direct VLM extraction plus optional OCR evidence,
current-player resolution, deterministic validation and explicit user confirmation.

## v4 follow-through

The proposed correction run was completed rather than adding another epoch:

1. Manager IDs now use the runtime integer type throughout schemas and corpus rows.
2. The 13,600-row v4 corpus keeps 9,600 replay rows (70.6%) and adds 4,000 targeted corrections.
3. Serving and both evaluators stop at `<|im_end|>`.
4. The correction mix adds FPL vocabulary, tool/decision routing, safety, multilingual replay and
   400 formation-image examples.
5. V4 trained from the clean base for one BF16 LoRA epoch in 31 minutes 37 seconds.
6. The final and checkpoint-510 adapters were selected only by the locked benchmark, not loss.

V4 was rejected: the final adapter scored 14/37 exact routes, 34/37 valid arguments, 9/37 strict
responses and 8/37 complete contracts. It also emitted duplicate starter slots on the desktop
image. See [`fpl-llm-training-v4.md`](fpl-llm-training-v4.md) for the complete record.

The v3 adapter is a sound proof of the local pipeline and a useful failure-discovery artifact. The
next spend should be targeted data and evaluation work, not a larger model or longer training run.
