"""Token usage and cost accounting.

Two paths:

1. EXACT (use this): the API returns a `usage` object on every response with the
   true token counts (`prompt_tokens`/`completion_tokens`). `CostTracker.add()`
   accumulates those and prices them. Free and exact — always prefer it.

2. APPROXIMATE (curriculum item): `estimate_tokens_tiktoken()` uses tiktoken to
   *estimate* tokens from raw text before a call. tiktoken is OpenAI's tokenizer;
   it's a reasonable proxy for OpenAI-family models but only a rough guide for
   Llama/Qwen/etc. served by Groq, which use different tokenizers. Treat it as a
   pre-flight budget check, never a billing source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import _DEFAULT_PRICING, MODEL_PRICING, settings


@dataclass
class UsageRecord:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def cost_usd(self) -> float:
        p = MODEL_PRICING.get(self.model, _DEFAULT_PRICING)
        return (
            self.input_tokens * p["input"]
            + self.output_tokens * p["output"]
            + self.cache_creation_input_tokens * p["cache_write"]
            + self.cache_read_input_tokens * p["cache_read"]
        ) / 1_000_000


@dataclass
class CostTracker:
    """Accumulates usage across all API calls in a single agent turn/session."""

    model: str = field(default_factory=lambda: settings.model)
    records: list[UsageRecord] = field(default_factory=list)

    def add(self, usage) -> UsageRecord:
        """Add the `.usage` object from a chat-completions response.

        Handles OpenAI/Groq style (`prompt_tokens`/`completion_tokens`, with
        optional `prompt_tokens_details.cached_tokens`). Falls back to
        Anthropic style (`input_tokens`/`output_tokens`) if present.
        """
        prompt = getattr(usage, "prompt_tokens", None)
        if prompt is not None:  # OpenAI / Groq / xAI
            details = getattr(usage, "prompt_tokens_details", None)
            cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
            rec = UsageRecord(
                model=self.model,
                input_tokens=max(0, (prompt or 0) - cached),
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=cached,
            )
        else:  # Anthropic style
            rec = UsageRecord(
                model=self.model,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_creation_input_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
                cache_read_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            )
        self.records.append(rec)
        return rec

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.records)

    @property
    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    def total_cost_usd(self) -> float:
        return sum(r.cost_usd() for r in self.records)

    def summary(self) -> dict:
        return {
            "model": self.model,
            "api_calls": len(self.records),
            "input_tokens": self.total_input_tokens,
            "output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.total_cost_usd(), 6),
        }


def estimate_tokens_tiktoken(text: str) -> int:
    """APPROXIMATE pre-flight token estimate via tiktoken (OpenAI's tokenizer).

    A rough proxy only — the served model (Llama/Qwen/Grok/etc.) likely uses a
    different tokenizer. Do not bill on this; use the response `usage` object for
    real counts.
    """
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))
