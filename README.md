# Production-Ready Fintech Support Agent

A support agent for a fictional digital bank (**NimbusPay**), built to demonstrate
the full production loop: **observability → evaluation → safety**.

- **Agent** — an LLM with a tool-use loop over fintech tools (balance,
  transactions, card status, block card, file dispute, KB search), with
  **multi-turn conversation memory**. Account/card/transaction data lives in a
  real **Postgres** database. Runs on any **OpenAI-compatible** endpoint; defaults
  to **Groq**.
- **Observability** — every turn is a nested **LangSmith** trace: the LLM calls,
  each tool's input/output, latency, and token counts.
- **Evaluation** — a golden dataset, custom + LLM-as-judge evaluators run through
  LangSmith experiments, plus **DeepEval** faithfulness / answer-relevancy /
  hallucination metrics.
- **Safety** — **Presidio** PII redaction, **Guardrails**-style regex/schema/
  semantic validators, sensitive-action gating, and exact **token/cost** tracking.

## Architecture

```
customer message
      │
      ▼
 PII redaction (Presidio)          ← inbound: secrets never hit logs/traces
      │
      ▼
 ┌─────────────────────────────┐
 │  chat-completions tool loop  │   ← LangSmith-traced (wrap_openai)
 │   search_knowledge_base      │      • cost tracked from usage object
 │   get_account_balance        │      • sensitive tools gated (block_card,
 │   get_recent_transactions    │        file_dispute)
 │   get_card_status            │
 │   block_card / file_dispute  │
 └─────────────────────────────┘
      │
      ▼
 output guardrails (regex / schema / semantic LLM-judge)
      │
      ▼
 AgentResult  { answer, tool_calls, cost, pii_redacted, guardrail_violations }
```

## Setup

```bash
python -m venv .venv && . .venv/Scripts/activate     # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_lg               # for Presidio (sm also works)

cp .env.example .env                                  # then fill in keys + DATABASE_URL
python scripts/setup_db.py                            # create the Postgres DB, tables, and seed data
```

Minimum to run: `LLM_API_KEY` (a Groq `gsk_...` key from https://console.groq.com/keys)
and `DATABASE_URL` (a Postgres connection string).
Add `LANGSMITH_API_KEY` + `LANGSMITH_TRACING=true` to send traces. To use xAI Grok or
another OpenAI-compatible provider instead, change `LLM_BASE_URL` + `FINTECH_AGENT_MODEL`.

## Run it

```bash
# Web UI (chat + observability/safety sidecar per message)
streamlit run app.py            # opens http://localhost:8501

# Talk to the agent on the CLI
python scripts/chat.py
python scripts/chat.py "How much does an international transfer cost?"
python scripts/chat.py --approve "Block card_8842 on acc_1001, it was stolen"

# Evaluate (offline score table — no LangSmith needed)
python -m evals.run_eval --local

# Evaluate as a LangSmith experiment (compare versions in the dashboard)
python -m evals.build_dataset --seed
python -m evals.run_eval --langsmith --experiment v1-llama70b
#   then switch FINTECH_AGENT_MODEL=llama-3.1-8b-instant in .env and re-run:
python -m evals.run_eval --langsmith --experiment v2-llama8b

# DeepEval faithfulness / relevancy / hallucination (judged by Claude)
python -m evals.deepeval_metrics
```

## How each curriculum goal maps to the code

| Goal | Where |
|---|---|
| Production fintech support agent | `src/fintech_agent/agent.py`, `tools.py` |
| Structured observability (LangSmith traces) | `observability.py` (`wrap_openai`) + `@traceable` on `agent.run` and every tool |
| Trace trees, tool I/O, latency, tokens | nested traces in LangSmith; tokens via `usage` |
| Build eval datasets from curated traces | `evals/build_dataset.py` (`dataset_from_traces`) |
| Custom + LLM-as-judge evaluators | `evals/evaluators.py` |
| Compare agent versions | `evals/run_eval.py --langsmith` (one experiment per model) |
| DeepEval faithfulness/relevancy/hallucination | `evals/deepeval_metrics.py` (Groq-backed judge) |
| Guardrails: regex / schema / semantic | `safety/guardrails.py` |
| PII detection & redaction (Presidio) | `safety/pii.py` |
| Token usage & cost | `safety/cost.py` |

## A note on tiktoken

The curriculum lists tiktoken for cost tracking. tiktoken is **OpenAI's**
tokenizer, so it's only a rough proxy for the open models Groq serves (Llama,
Qwen, …), which tokenize differently. This project tracks **real** cost from the
API's `usage` object (exact, free) in `safety/cost.py`; the tiktoken estimator is
included there too, clearly labeled as a pre-flight approximation only.

## Data

Account/card/transaction data lives in **Postgres** — tables `accounts`, `cards`,
`transactions`, defined and seeded by [scripts/setup_db.py](scripts/setup_db.py).
Tools read/write it via [src/fintech_agent/db.py](src/fintech_agent/db.py) (e.g.
`block_card` actually `UPDATE`s the row). Re-run `python scripts/setup_db.py` any
time to reset the demo data. Policy/fees still come from the markdown
[data/knowledge_base.md](data/knowledge_base.md).

Demo accounts (seeded):
- `acc_1001` (Alex Rivera, standard) — cards `card_8842`, `card_2207`
- `acc_1002` (Priya Shah, premium) — card `card_5519` (frozen)
- `txn_5503` on `acc_1001` is a suspicious charge, good for testing disputes/fraud.

## Conversation memory

The agent is multi-turn: [app.py](app.py) and the interactive CLI keep a
`history` list of prior user/assistant turns and pass it to `agent.run(message,
history=...)`, so follow-ups like a bare "acc_1001" or "yes, block it" resolve
against earlier turns. "Clear chat" resets it.
