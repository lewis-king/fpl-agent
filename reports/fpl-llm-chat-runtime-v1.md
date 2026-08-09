# FPLAgent grounded chat runtime v1

Date: 6 August 2026

## Outcome

The first end-to-end local chatbot runtime is operational. Qwen3.5-4B can turn a natural-language
captain question into validated read-only tool calls, replay the structured results into the model,
and return a receipt-backed explanation. The LLM is the conversational layer; deterministic code
owns schemas, manager state, legal candidate filtering, forecast values and failure policy.

## Implemented components

- `src/fplagent_llm/chat_runtime.py`: conversation state, system policy, bounded model/tool loop,
  tool-result replay, grounding guard, receipt extraction and privacy-safe JSONL logging.
- `src/fplagent_llm/runtime_tools.py`: schema-validating dispatcher, local manager-state adapter and
  captain-comparison service over the versioned forecast artifacts.
- `src/fplagent_llm/qwen_runtime.py`: local Qwen/Unsloth loader and parser for Qwen tool-call turns.
- `llm/chat_qwen35.py`: one-shot and interactive RTX 5090 CLI.
- `fplagent-llm runtime-tools`: model-free inspection of the runtime evidence.

Only `get_manager_state` and `compare_captains` are enabled. Both are read-only. The dispatcher
rejects unknown tools, extra arguments, invalid schemas, bench captain candidates and unsupported
events or decision policies.

## Live smoke proof

The unfine-tuned base model was deliberately used because v3 and v4 did not pass the text promotion
gate. For the prompt “Who should I captain for GW1? Use my active manager state and a robust
policy”, Qwen called:

1. `get_manager_state`
2. `compare_captains`

Both calls succeeded. The runtime returned receipt `captain-v1-f5f10bd0000db287` without a safety
failure or conversation-boundary violation. The robust result is Bruno Fernandes as captain and
James Tarkowski as vice-captain, based on the stored GW1 starting XI and versioned preseason
forecasts. It remains provisional because the source manager snapshot is synthesized and stale,
not an authenticated live account.

The default log at `data/llm/runtime/chat_events.jsonl` stores prompt/answer hashes, durations, tool
names, error codes and receipt IDs. It does not store chat content unless explicitly enabled.

## Safety boundary

- A captain recommendation cannot survive a failed captain tool.
- A missing refresh caveat is appended deterministically when evidence requires a refresh.
- A non-terminating tool loop and an invalid Qwen turn boundary produce a no-recommendation result.
- Mini-league policy is rejected until rank, rival and objective context are present.
- The service never fabricates missing free-transfer or chip state.

## Current limitation and next step

Manager ID 1 currently maps to `data/decisions/2026-27-gw1-synthesized.json`. The immediate next
step is a manager-state persistence API that can accept a confirmed squad from the app or guarded
screenshot workflow, followed by a deadline-aware official-data refresh and decision-engine rerun.
After that, expose the runtime through an in-app streaming chat endpoint and add versioned RAG for
rules, glossary, methodology and owned research.
