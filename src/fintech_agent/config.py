"""Central configuration. Reads from environment (.env) with sane defaults.

The agent runs on an OpenAI-compatible endpoint. Default: Groq
(https://api.groq.com/openai/v1) with an open model that supports tool calling.
To use xAI Grok instead, set LLM_BASE_URL=https://api.x.ai/v1, a grok-* model,
and an xai- key. Any OpenAI-compatible provider works the same way.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root regardless of where we're invoked from.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
KNOWLEDGE_BASE_PATH = DATA_DIR / "knowledge_base.md"

# Per-1M-token USD pricing. VERIFY against your provider's pricing page — these
# are approximate and only affect the dollar figure, not the token counts.
# `cache_read` is the provider's cached-input rate (0 if not applicable).
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Groq (open models)
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79, "cache_write": 0.0, "cache_read": 0.0},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08, "cache_write": 0.0, "cache_read": 0.0},
    "moonshotai/kimi-k2-instruct": {"input": 1.0, "output": 3.0, "cache_write": 0.0, "cache_read": 0.0},
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.75, "cache_write": 0.0, "cache_read": 0.0},
    "qwen/qwen3-32b": {"input": 0.29, "output": 0.59, "cache_write": 0.0, "cache_read": 0.0},
    # xAI Grok (if you switch providers)
    "grok-4": {"input": 3.0, "output": 15.0, "cache_write": 0.0, "cache_read": 0.75},
    "grok-3-mini": {"input": 0.30, "output": 0.50, "cache_write": 0.0, "cache_read": 0.075},
}
_DEFAULT_PRICING = {"input": 0.59, "output": 0.79, "cache_write": 0.0, "cache_read": 0.0}


@dataclass(frozen=True)
class Settings:
    api_key: str | None = field(
        default_factory=lambda: os.getenv("LLM_API_KEY")
        or os.getenv("GROQ_API_KEY")
        or os.getenv("XAI_API_KEY")
    )
    base_url: str = field(
        default_factory=lambda: os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    )
    model: str = field(
        default_factory=lambda: os.getenv("FINTECH_AGENT_MODEL", "llama-3.3-70b-versatile")
    )
    judge_model: str = field(
        default_factory=lambda: os.getenv("FINTECH_JUDGE_MODEL")
        or os.getenv("FINTECH_AGENT_MODEL", "llama-3.3-70b-versatile")
    )
    max_tokens: int = 4096
    max_tool_iterations: int = 6

    # Postgres connection string for account/card/transaction data.
    database_url: str = field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", "postgresql://postgres:postgres123@localhost:5432/nimbuspay"
        )
    )

    langsmith_project: str = field(
        default_factory=lambda: os.getenv("LANGSMITH_PROJECT", "fintech-support-agent")
    )
    tracing_enabled: bool = field(
        default_factory=lambda: os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
    )

    def pricing(self) -> dict[str, float]:
        return MODEL_PRICING.get(self.model, _DEFAULT_PRICING)


settings = Settings()
