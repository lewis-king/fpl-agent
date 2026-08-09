# FPLAgent conversational LoRA v5 experiment

Status: final bounded cycle concluded; no new adapter promoted, 8 August 2026

## Objective

Produce a Qwen3.5-4B LoRA that is noticeably better than the clean base model in the actual
FPLAgent application. The target is not merely more FPL terminology. The adapter must behave like
a useful conversational product: answer ordinary questions naturally, recover from confusion,
explain stable FPL concepts without unnecessary data access, choose the correct grounded route for
current decisions, and retain the existing screenshot capability.

The experiment began after v3 answered a basic capability question by reciting provisional
manager-state and captaincy workflow language. Runtime evidence showed that it had also called a
manager-state tool unnecessarily. The main diagnosis was data balance: roughly 70% of v3's text
training examples contained tool calls, while its locked evaluation did not adequately cover normal
conversation or explicit no-tool boundaries.

## Candidate data

The deterministic v5 build is:

- generator: `fpl-app-conversation-corpus-v5`;
- seed: `20260806`;
- file: `data/llm/generated/fpl_app_corpus_v5/combined_train.jsonl`;
- rows: 24,000;
- estimated rendered tokens: 9,827,384;
- SHA-256: `c625419f4801f9e4bbea923994450a10224bf0c91f2c34592a3079924f08c8fe`.

It contains 17,200 newly generated application conversations and 6,800 balanced replay examples
from v3. Of all rows, 18,554 (77.3%) teach direct answers and 5,446 contain tool calls. The mixture
also replays all 960 screenshot training rows so text improvements do not simply erase the proven
image-extraction behaviour.

| New family | Rows | Purpose |
| --- | ---: | --- |
| Identity and capability | 2,400 | Explain what FPLAgent is without exposing internal workflow |
| Social conversation and repair | 2,400 | Greetings, correction, uncertainty, tone and collaboration |
| Harmless general steering | 1,600 | Preserve useful base-model behaviour outside a strict FPL script |
| Direct FPL conversation | 4,800 | Natural FPL language and stable strategic concepts |
| Explicit no-tool boundaries | 2,400 | Distinguish explanation from a current personalised decision |
| Actual application tool routes | 2,000 | The four tool sequences available in the web application |
| Multi-turn conversations | 1,600 | Follow-ups, changed preferences and conversational continuity |

The builder validates every message, every tool argument schema and every referenced image. It
rejects duplicate prompts and exact or near prompt overlap with both locked text benchmarks.
Synthetic current values only occur inside timestamped tool results; they are not presented as
memorised facts.

## Training recipe

V5 starts from the clean `unsloth/Qwen3.5-4B` base, not from v3 or v4. It trains rank-16 LoRA
matrices on language attention and MLP modules while the 4.57-billion base parameters and vision
encoder remain frozen.

| Setting | Value |
| --- | --- |
| Precision | BF16 16-bit LoRA |
| Trainable parameters | 32,464,896 (0.71%) |
| Epochs / optimizer steps | 1 / 1,500 |
| Batch / accumulation / effective batch | 2 / 8 / 16 |
| Learning rate | `1e-5`, cosine schedule, 5% warm-up |
| Context ceiling | 2,048 tokens |
| Loss mask | Assistant responses and tool calls only |
| Checkpoints | Every 300 steps plus final adapter |
| Wall-clock guard | 180 minutes |

The lower learning rate and direct-answer-heavy replay are intended to add FPLAgent instincts
without overwriting Qwen's useful general conversational behaviour.

## Locked evaluation and promotion gate

`AppChatBench v1` contains 58 prompts that do not appear in training: 50 direct/no-tool cases and
eight current application tool routes. Base Qwen, under the same improved system prompt and same
four tools, establishes this frozen baseline:

| Measure | Base Qwen3.5-4B |
| --- | ---: |
| Full contracts | 15 / 58 |
| Exact route | 53 / 58 |
| Response contract | 17 / 58 |
| Valid tool arguments | 58 / 58 |
| Clean turn boundary | 58 / 58 |
| No-tool route | 50 / 50 |
| Explicit tool route | 3 / 8 |

Before candidate inference, v5 is required to meet all of these gates:

1. At least 40/58 full AppChatBench contracts and at least 20 more than base.
2. All 50 explicit no-tool cases remain tool-free.
3. At least seven of eight application tool sequences are exact.
4. All tool arguments validate and all 58 generations end on a clean assistant boundary.
5. Both prompt-injection cases and all four calibrated-safety cases pass their full contracts.
6. On the older 37-case FPLBench, exact routing is at least v3's 21/37 and full-contract passes are
   no worse than the base/v3 result of 6/37.
7. The real mobile and desktop screenshot proposals both pass deterministic squad validation, with
   no regression in the 15-player roster, starter/bench roles, captaincy or bench order.
8. A human-readable A/B smoke set must show natural, concise answers for capability, conversational
   repair, a harmless general question, a conceptual FPL question and a current grounded decision.

Training loss is recorded for reproducibility but is not a promotion criterion. If the final epoch
fails a gate, the saved 300-step checkpoints may be evaluated to identify an earlier, less
specialised optimum; otherwise the corpus or recipe must be revised and retrained.

## V5 result: rejected

V5 completed 1,500 steps in 42 minutes, but failed the application benchmark and was not promoted.

| Measure | Base | V5 final |
| --- | ---: | ---: |
| Full contracts | 15 / 58 | 9 / 58 |
| Exact route | 53 / 58 | 22 / 58 |
| Direct/no-tool route | 50 / 50 | 18 / 50 |
| Grounded tool route | 3 / 8 | 4 / 8 |
| Valid tool arguments | 58 / 58 | 56 / 58 |
| Clean turn boundary | 58 / 58 | 58 / 58 |

The failed outputs made the cause visible: capability, social and conceptual prompts frequently
triggered manager-state and captaincy calls. The corpus balance had improved, but the trainer's
vision collator rendered every row with `apply_chat_template(messages)` and no `tools` argument.
At real inference the processor receives four tool schemas, which inserts roughly 1,000 additional
tokens beginning with `# Tools` before the application system policy. Direct-answer training rows
had never seen that context, so the adapter treated its presence as a strong tool-call cue.

This is a training/inference feature mismatch, not a reason to weaken the production tool guard.
The v5 adapter and evaluation are retained as a negative result.

## V6 corrective iteration

The trainer now derives Qwen's exact tool preamble dynamically from the installed processor and the
four real application schemas. It injects that prefix into every text conversation before the
normal collator renders it. Screenshot rows stay tool-free because screenshot inference is also
tool-free. A one-step full-stack smoke proved that the 3,072-token context, response-only loss mask
and adapter save path all work.

The v6 mixture contains 20,554 rows:

- 18,554 direct answers (90.3%);
- 2,000 grounded routes using only `get_manager_state`, `compare_captains`, `search_players` and
  `optimize_squad`;
- all 960 screenshot examples;
- no legacy rows containing unavailable tools.

Its SHA-256 is `f6e14d00c161d9df1d1e833fe927c6efe46f747b4e3137f63cc854a9c28879e1`.
V6 trains from the clean base at a lower `7e-6` peak learning rate, uses a 3,072-token ceiling and
keeps an effective batch size of 16 through batch size 1 and 16 accumulation steps. It must pass the
same promotion gate; discovering the v5 cause does not relax the standard.

## V6 result: routing repaired, prose rejected

V6 completed 1,285 steps in 97 minutes 32 seconds and peaked at 15.91 GiB reserved VRAM. The exact
runtime-tool preamble corrected the original feature mismatch: 49/50 direct prompts stayed
tool-free, 7/8 current-decision routes were exact, all 58 argument sets validated and every response
ended cleanly. This is a large routing improvement over both base and v5.

| Measure | Base | V5 | V6 final |
| --- | ---: | ---: | ---: |
| Full contracts | 15 / 58 | 9 / 58 | 23 / 58 |
| Exact route | 53 / 58 | 22 / 58 | 56 / 58 |
| Direct/no-tool route | 50 / 50 | 18 / 50 | 49 / 50 |
| Grounded tool route | 3 / 8 | 4 / 8 | 7 / 8 |
| Valid tool arguments | 58 / 58 | 56 / 58 | 58 / 58 |
| Clean turn boundary | 58 / 58 | 58 / 58 | 58 / 58 |

V6 is still rejected. Its 20,554-row mixture repeated a small number of direct-answer targets with
generic endings thousands of times. The resulting prose overused phrases such as “the important
distinction” and occasionally repeated a clause until the generation ceiling. Checkpoint 300
scored 22/58 complete cases, so the defect was already present early rather than being caused only
by the end of the epoch. Tool alignment is necessary, but synthetic volume cannot compensate for
low target diversity.

## V7 quality correction

V7 therefore returns to the clean base with a smaller, more deliberate 5,476-row mixture. It has
134 hand-authored capability, social, safety, general and season-long FPL scenarios, with 24 unique
prompt frames per scenario and six natural answer forms. The generic endings are removed. The
mixture also contains 400 multi-turn conversations, 500 grounded application routes, 400 selected
safety/multilingual replays and all 960 screenshot examples. Across 5,876 assistant text turns it
contains 1,992 unique responses, versus repeatedly teaching one catchphrase as a universal close.

The deterministic artifact is
`data/llm/generated/fpl_app_corpus_v7/combined_train.jsonl`, SHA-256
`830d0abe33df66264f2c6c7ef32e0ce51ef6e1b7149b45a524941b07cfc7ced1`. V7 keeps the exact Qwen
application-tool preamble for every text row, freezes the vision encoder and trains a rank-16 BF16
LoRA from the clean base for one epoch at `4e-6`. It is subject to the original promotion gate.

## V7 result: route-complete but under-trained

V7 completed 343 steps in 26 minutes 31 seconds. It removed V6's repeated catchphrase and routed
all eight grounded application cases correctly, while keeping 49/50 direct cases tool-free. The
single low-rate epoch did not internalise enough of the new FPL strategy targets, however: only
19/58 strict full contracts passed. Qualitative failures included generic capability replies,
confusing unspent budget with points, weak bench and hit explanations, and occasional repetition.
V7 is therefore not promoted.

| Measure | Base | V6 | V7 |
| --- | ---: | ---: | ---: |
| Full contracts | 15 / 58 | 23 / 58 | 19 / 58 |
| Exact route | 53 / 58 | 56 / 58 | 57 / 58 |
| Direct/no-tool route | 50 / 50 | 49 / 50 | 49 / 50 |
| Grounded tool route | 3 / 8 | 7 / 8 | 8 / 8 |
| Valid tool arguments | 58 / 58 | 58 / 58 | 58 / 58 |
| Clean turn boundary | 58 / 58 | 58 / 58 | 58 / 58 |

V8 uses the same validated V7 corpus from the clean base but gives it enough optimisation time:
three epochs, a `6e-6` peak rate, effective batch 16 and a 2,048-token ceiling. Token auditing showed
the tool-aware text rows fit that ceiling. Checkpoints at steps 250, 500, 750 and 1,000 allow the
best held-out point to be selected instead of assuming the final epoch is optimal.

## V8 result: rejected and LLM training frozen

V8 reached checkpoint 750 before an unrelated set of three GPU jobs consumed roughly 19.8 GiB and
the next training batch exhausted the remaining VRAM. The interruption did not corrupt the saved
250, 500 or 750 checkpoints. Checkpoints 500 and 750 were evaluated under the same locked
AppChatBench contract; both failed decisively.

| Measure | Base | V6 best candidate | V8 step 500 | V8 step 750 |
| --- | ---: | ---: | ---: | ---: |
| Full contracts | 15 / 58 | **23 / 58** | 16 / 58 | 17 / 58 |
| Exact route | 53 / 58 | **56 / 58** | 52 / 58 | 53 / 58 |
| Direct/no-tool route | 50 / 50 | 49 / 50 | **50 / 50** | **50 / 50** |
| Grounded tool route | 3 / 8 | **7 / 8** | 2 / 8 | 3 / 8 |
| Valid tool arguments | 58 / 58 | 58 / 58 | 58 / 58 | 58 / 58 |
| Clean turn boundary | 58 / 58 | 58 / 58 | 58 / 58 | 58 / 58 |

The later schedule learned to avoid tools for every direct prompt, but simultaneously stopped
calling them for current-team decisions. It also produced repetitive or overly generic strategy
answers. This is not a strict-lexical-score technicality: qualitative inspection found real product
failures in budget allocation, four-point hits, capability answers and current decision routing.

No v5-v8 adapter is promoted. Text chat remains base Qwen3.5-4B plus the application system policy,
typed tools and deterministic decision guards. V3 remains the separately scoped screenshot adapter.
Further LoRA work is intentionally frozen while the project returns to forecast and optimisation
quality. All corpora, configs, checkpoints and negative evaluations are retained for a later study
of better synthetic-teacher data, preference optimisation and separate text/vision adapters.

## V9 final bounded experiment

On 7 August, a final diagnostic audit found a second training/inference mismatch. V6-v8 text rows
included Qwen's real four-tool preamble, but still used the short generic corpus system message;
production inference uses the longer, contextual application policy. The formatter now derives the
exact production context for text rows while leaving screenshot rows in their real tool-free vision
context.

A small precision corpus was prepared to test that diagnosis without another high-volume synthetic
run:

- generator: `fpl-app-precision-corpus-v9`;
- file: `data/llm/generated/fpl_app_precision_v9/combined_train.jsonl`;
- rows: 3,668, comprising 2,008 direct text rows, 700 grounded tool routes and 960 screenshot rows;
- 134 hand-authored scenarios with 12 prompt variants each;
- maximum similarity to a locked evaluation prompt: 0.6887;
- SHA-256: `2e870f4ede6fcae31ba7df15dd310120ee2c528c012098eaa8101b30cf066b27`.

The formatter, generator, CLI entry point and corpus invariants are covered by six focused tests.
The corpus uses complete 15-player manager states, only the four production chat tools, matching
optimiser constraints/results and no exact copy of the motivating `What do you do?` prompt.

The user later explicitly authorised this one final run. Preflight first proved the exact production
system/tool context, response-only loss mask and save path. V9 then trained from the clean base for
three epochs (690 steps) at `4e-6` in 5,875.73 seconds: 97 minutes 56 seconds including save. The
training runtime itself was 5,718.53 seconds, final loss was 0.305657 and peak reserved VRAM was
15,493,758,976 bytes on the RTX 5090. Training loss was never a promotion criterion.

- config: `llm/configs/qwen35_4b_fpl_v9_lora.json`;
- config SHA-256: `30f01a328e6d3c5adb5e5aa9beec7a3efc4d94bdd7c349626b8289950a478ff0`;
- adapter: `llm/outputs/qwen35-4b-fpl-lora-v9/adapter`;
- adapter safetensors SHA-256:
  `3fb7a04cbf419ef7aaea74ae19674616977b335507f5bc84e53b7a0a77c2b09e`;
- training manifest: `llm/outputs/qwen35-4b-fpl-lora-v9/training_manifest.json`;
- evaluation receipt: `llm/evaluations/qwen35-4b-fpl-lora-v9/promotion.json`.

### V9 result: useful gains, rejected overall

| Measure | Base | V9 | Required |
| --- | ---: | ---: | ---: |
| Strict AppChat contracts | 16 / 58 | 16 / 58 | at least 40 and +20 |
| Exact application routes | 54 / 58 | 58 / 58 | supporting measure |
| Direct/no-tool routes | 50 / 50 | 50 / 50 | 50 / 50 |
| Grounded application routes | 4 / 8 | 8 / 8 | at least 7 / 8 |
| Valid arguments / clean boundaries | 58 / 58 | 58 / 58 | all |
| Legacy routes | v3 reference 21 / 37 | 20 / 37 | at least 21 / 37 |
| Legacy strict contracts | v3 reference 6 / 37 | 4 / 37 | at least 6 / 37 |
| Held-out synthetic screenshots | 2 / 10 | 5 / 10 | all; candidate lift alone is insufficient |
| Supplied real screenshots | 1 / 2 exact | 2 / 2 exact | both |

The blind 14-case review also rejected V9: it was preferred in 7 cases versus 6 for base with one
tie, gained only five aggregate points against the required eight, and produced two grounding
failures. The locked safety response contracts did not all pass. V9 learned the intended tool
boundary and improved vision-language extraction, but its ordinary answer quality was not vividly
better than base and it remained unsafe on unseen layouts.

The verdict is **REJECT**. The adapter and checkpoints are preserved as reproducible research, the
application defaults remain base Qwen for guarded text chat and V3 for the separately guarded
screenshot path, and further LoRA work is parked. The project now returns to the points-first
forecast, optimiser and weekly-decision roadmap.
