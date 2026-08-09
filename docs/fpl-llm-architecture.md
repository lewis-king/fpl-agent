# FPLAgent LLM architecture

Status: local research implementation, 6 August 2026

## The short version

FPLAgent has genuinely fine-tuned an open model, but it has not trained a four-billion-parameter
model from scratch. The project starts with the public multimodal Qwen3.5-4B base model and trains
small FPL-specific LoRA adapters locally on an RTX 5090. At inference time, the compatible base
model is loaded and the chosen adapter is attached to it.

```text
Qwen3.5-4B base parameters
          +
FPLAgent LoRA adapter parameters
          +
grounded FPL tools and application policy
          =
the effective FPLAgent assistant
```

The adapter teaches model behaviour and FPL language. Current manager state, prices, availability,
fixtures and numeric recommendations do not belong in adapter memory: they are supplied through
timestamped tools or, where appropriate, versioned retrieval.

## What each part is

### Qwen3.5-4B is the base model

`unsloth/Qwen3.5-4B` supplies the pretrained language and vision capabilities. Its full base weights
are not owned or retrained by this project and remain governed by the upstream model licence. The
vision capability is why a team screenshot can be passed directly to the model instead of reducing
every upload to OCR text first.

### The FPL LoRA is our fine-tune

LoRA, or low-rank adaptation, freezes the large base model and learns compact adjustment matrices.
Conceptually, a selected base weight is used as:

```text
effective weight = base weight + scale × (LoRA B × LoRA A)
```

The locally produced adapter directories contain the learned FPL adjustments and configuration,
not another complete copy of Qwen. This makes training fast enough for a consumer GPU, keeps
experiments small, and allows several adapters to be evaluated against exactly the same base.

Current important artifacts are:

- `llm/outputs/qwen35-4b-fpl-lora-v3/adapter`: best current screenshot adapter; not promoted as the
  default text-chat model.
- `llm/outputs/qwen35-4b-fpl-lora-v4/adapter`: correction/replay experiment retained for analysis;
  not promoted.
- `llm/outputs/qwen35-4b-fpl-lora-v5/adapter`: broad application-conversation experiment rejected
  after exposing a training/runtime tool-context mismatch.
- `llm/outputs/qwen35-4b-fpl-lora-v6/adapter`: repaired tool routing, but rejected for repetitive
  synthetic prose.
- `llm/outputs/qwen35-4b-fpl-lora-v7/adapter`: diverse quality-correction experiment that routed
  all eight grounded app cases but remained under-trained after one epoch.
- `llm/outputs/qwen35-4b-fpl-lora-v8/checkpoint-{500,750}`: extended-schedule checkpoints rejected
  after current-decision tool routing regressed; neither is an application default.

All candidates use BF16 LoRA from the clean base model and remain comfortably within the local RTX
5090 budget. Training produced real locally learned adapter weights; a low training loss alone is
deliberately not treated as proof that an adapter is better. The detailed v5-v8 experiment record is
in `reports/fpl-llm-v5-experiment.md`.

### Unsloth is the training and inference accelerator

Unsloth patches the supported model stack for faster, lower-memory local training and inference. It
loads the Qwen architecture through the Hugging Face ecosystem and prepares it for efficient local
execution. Unsloth is not the FPL model and does not provide the FPL knowledge.

### PEFT attaches the adapter

Hugging Face PEFT loads the LoRA configuration and attaches its learned matrices to the compatible
Qwen modules. Unless a separate export explicitly merges them, the base and adapter remain separate
files. During a forward pass, they behave as one effective model.

Keeping them separate is currently preferable because it:

- avoids duplicating the full base checkpoint;
- makes base-versus-adapter evaluation straightforward;
- permits instant selection between v3, v4 and future adapters;
- preserves a clean base for every new experiment.

A merged standalone checkpoint can be exported later if a deployment target benefits from it. It
would be less flexible and would still inherit the upstream base-model licensing conditions.

## What happens during fine-tuning

```text
FPL source policy and owned structured data
                 │
                 ├── synthetic FPL conversations and tool traces
                 ├── decision-receipt explanations
                 ├── safety, ambiguity and staleness examples
                 ├── multilingual examples
                 └── synthetic and benchmark team screenshots
                                  │
                                  ▼
                      validated train/validation/test splits
                                  │
                                  ▼
                  Qwen chat template + response-only masking
                                  │
                                  ▼
                      BF16 LoRA training with Unsloth
                                  │
                                  ▼
                         compact adapter checkpoint
                                  │
                                  ▼
                  locked text, tool and screenshot evaluation
```

The trainer masks system, user and tool-result tokens, so loss is applied only to assistant
responses and tool calls. Scenario and squad grouping prevents paraphrases or alternative views of
the same underlying case from leaking across splits. The current application corpus also renders
text rows with the same four Qwen tool schemas that are present at runtime. This alignment matters:
without it, the model can learn that seeing any tool preamble means it should call a tool, even for a
greeting or conceptual question.

The vision encoder remains pretrained and frozen in this training design. The adapter trains the
language-side attention and MLP behaviour that consumes the pretrained visual representation. This
retains Qwen's general multimodal capability while specialising extraction and FPL response
behaviour without an expensive full vision-model fine-tune.

## What happens at runtime

There are presently two valid runtime modes.

### Promoted chatbot mode: base Qwen plus tools

```bash
llm/.venv/bin/python llm/chat_qwen35.py \
  --manager-id 1 \
  --event 1 \
  --prompt "Who should I captain for GW1? Use a robust policy."
```

No `--adapter` argument means the process loads base Qwen. This is currently the default because
neither v3 nor v4 passed all locked text-chat promotion gates. The result is still an FPLAgent
assistant: the system policy, typed FPL tools and deterministic decision engine provide the grounded
specialism around the model.

### Adapter evaluation mode: base Qwen plus the FPL LoRA and tools

```bash
llm/.venv/bin/python llm/chat_qwen35.py \
  --adapter llm/outputs/qwen35-4b-fpl-lora-v3/adapter \
  --manager-id 1 \
  --event 1 \
  --prompt "Who should I captain for GW1? Use a robust policy."
```

This loads the same base and attaches the v3 FPL adapter before inference. It is a genuine
fine-tuned-model run, but remains an evaluation mode until the adapter beats the base across the
required chatbot gates.

`llm/chat_qwen35.py` is a command-line launcher, not the name of the resulting model. It is named
after the model backend it loads. A product-facing command should eventually be model-independent,
for example `fplagent-llm chat`, so a later base-model change does not alter the product identity.

## Grounded decision architecture

The LLM must not calculate authoritative FPL decisions or invent live facts. It handles intent,
tool selection and natural-language explanation. Typed application services handle the facts and
math.

```text
User question
     │
     ▼
Qwen conversational layer
     │ chooses a typed, read-only tool
     ▼
Schema-validating tool registry
     ├── manager-state repository
     └── captain-comparison service
                 │
                 ▼
Versioned forecasts and deterministic decision artifacts
                 │
                 ▼
Structured result + receipt + staleness/confirmation markers
     │
     ▼
Qwen explanation
     │
     ▼
Application grounding guard and privacy-safe event log
```

Runtime v1 enables two read-only tools:

- `get_manager_state` returns the latest stored squad state, provenance, unavailable fields,
  confirmation state and staleness.
- `compare_captains` evaluates all 15 squad members, selects the forecast-best legal XI, and then
  returns its captain/vice pair, required bench promotions, evidence status, correlation caveat and
  receipt ID. An optional named candidate subset is returned only as a separate pairwise comparison
  and cannot redefine the full-squad recommendation.

The application renders captain recommendations from that deterministic receipt, rather than
allowing model prose to override its names or numbers. It also overrides any attempted
recommendation after a failed captain tool, appends a live refresh warning when needed, limits the
number of tool rounds and rejects an invalid model turn boundary. Chat content is hashed in the
default event log rather than stored verbatim.

Two high-frequency decision intents have a stricter fast path. An unambiguous captain request, a
named captain follow-up in an existing captain conversation, or a full-squad audit is routed to the
manager-state and captain-comparison tools without spending a model generation merely to rediscover
that route. The application renders the resulting receipt directly. A full-squad audit reports the
best legal XI, current versus recommended armband, strongest signals, weakest current starters,
availability and both outfield and goalkeeper bench cover. This avoids unsupported football
narratives and made the live local path roughly 15–25 ms in the 6 August QA run. Qwen remains the
language/tool-orchestration layer for open conversation and constrained squad changes.

Manager ID 1 currently maps to a synthesized versioned GW1 artifact. Its output is correctly marked
unconfirmed, stale and in need of a deadline refresh. It must not be mistaken for an authenticated
live FPL account.

## Multimodal team uploads

The preferred upload pipeline retains multimodality rather than depending entirely on OCR:

```text
Screenshot
   ├── Qwen vision extraction
   └── optional OCR cross-check
              │
              ▼
current player-catalog entity resolution
              │
              ▼
deterministic 15-player, formation, club-limit and slot validation
              │
              ▼
user review and explicit confirmation
              │
              ▼
persisted manager state usable by chat tools
```

The vision model proposes what it can see. It does not get final authority over player IDs, hidden
chip state, team legality or confirmation. This boundary is important because even a visually
excellent model can hallucinate a small badge or truncated name.

## Where RAG fits

RAG should be used for versioned textual knowledge such as rules, glossary entries, methodology and
owned research. It should not be the primary store for live manager state, prices, fixtures or
forecasts. Those values belong in typed, timestamped tools where schemas and provenance can be
validated exactly.

```text
Fine-tune: stable behaviour, FPL language, tool use and answer style
RAG:       versioned rules, explanations, methodology and research
Tools:     current structured facts, manager state and numeric decisions
```

## Promotion policy

The application does not automatically use the newest or lowest-loss adapter. A candidate must beat
base Qwen with the same tools and retrieval on locked evaluations covering:

- correct tool route and valid arguments;
- faithful use of tool results and decision receipts;
- clean conversation boundaries and safe failure;
- FPL answer quality and multilingual behaviour;
- screenshot identity, role, slot, captaincy and squad-validity accuracy.

This is why having fine-tuned adapters and choosing not to use one as the default chatbot are
compatible statements. The training succeeded; product promotion is a separate evidence-based
decision.

## Key implementation locations

- `llm/train_qwen35.py`: local Unsloth LoRA trainer.
- `llm/configs/qwen35_4b_fpl_v3_lora.json`: reproducible v3 training configuration.
- `src/fplagent_llm/qwen_runtime.py`: Qwen/Unsloth loading and tool-turn parsing.
- `src/fplagent_llm/chat_runtime.py`: bounded conversation loop and grounding policy.
- `src/fplagent_llm/runtime_tools.py`: manager-state and captain-comparison services.
- `llm/chat_qwen35.py`: local one-shot and interactive launcher.
- `llm/README.md`: commands, datasets, measured runs and evaluation tables.
- `reports/fpl-llm-chat-runtime-v1.md`: first runtime implementation receipt.
