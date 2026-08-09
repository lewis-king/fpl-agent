from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .chat_runtime import ModelTurn, ToolCall
from .text_evaluation import first_generated_turn, parse_tool_calls


class QwenChatModel:
    """Lazy Unsloth-backed Qwen runtime implementing the generic chat model protocol."""

    def __init__(
        self,
        model: Any,
        processor: Any,
        torch_module: Any,
        *,
        name: str,
        max_new_tokens: int = 512,
    ) -> None:
        self.model = model
        self.processor = processor
        self.torch = torch_module
        self.name = name
        self.max_new_tokens = max_new_tokens
        tokenizer = getattr(processor, "tokenizer", processor)
        self.end_of_turn_token_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
        if not isinstance(self.end_of_turn_token_id, int) or self.end_of_turn_token_id < 0:
            raise RuntimeError("Qwen tokenizer does not expose an <|im_end|> token ID")

    @classmethod
    def load(
        cls,
        *,
        model_name: str = "unsloth/Qwen3.5-4B",
        adapter: Path | None = None,
        max_new_tokens: int = 512,
    ) -> QwenChatModel:
        import torch
        import unsloth  # noqa: F401 - patches Transformers before later imports
        from peft import PeftModel
        from unsloth import FastVisionModel

        if not torch.cuda.is_available():
            raise RuntimeError("The local Qwen runtime requires CUDA")
        model, processor = FastVisionModel.from_pretrained(
            model_name,
            load_in_4bit=False,
            use_gradient_checkpointing=False,
        )
        if adapter is not None:
            model = PeftModel.from_pretrained(model, adapter)
        FastVisionModel.for_inference(model)
        runtime_name = model_name if adapter is None else f"{model_name}+{adapter}"
        return cls(
            model,
            processor,
            torch,
            name=runtime_name,
            max_new_tokens=max_new_tokens,
        )

    def generate(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> ModelTurn:
        rendered = self.processor.apply_chat_template(
            list(messages),
            tools=list(tools),
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.processor(
            text=rendered,
            add_special_tokens=False,
            return_tensors="pt",
        ).to("cuda")
        with self.torch.inference_mode():
            output = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                use_cache=True,
                eos_token_id=self.end_of_turn_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[-1] :]
        raw = self.processor.decode(
            generated,
            skip_special_tokens=True,
        ).strip()
        parsed = self.parse_turn(raw)
        generation_truncated = bool(
            generated.shape[-1] >= self.max_new_tokens
            and int(generated[-1].item()) != self.end_of_turn_token_id
        )
        return ModelTurn(
            content=parsed.content,
            tool_calls=parsed.tool_calls,
            raw_text=parsed.raw_text,
            boundary_valid=parsed.boundary_valid,
            generation_truncated=generation_truncated,
        )

    @staticmethod
    def parse_turn(raw: str) -> ModelTurn:
        current, boundary_valid = first_generated_turn(raw)
        calls = parse_tool_calls(current)
        without_thinking = re.sub(r"<think>.*?</think>", "", current, flags=re.DOTALL)
        content = without_thinking.split("<tool_call>", maxsplit=1)[0].strip()
        return ModelTurn(
            content=content,
            tool_calls=tuple(
                ToolCall(
                    id=str(call["id"]),
                    name=str(call["function"]["name"]),
                    arguments=dict(call["function"]["arguments"]),
                )
                for call in calls
            ),
            raw_text=raw,
            boundary_valid=boundary_valid,
        )
