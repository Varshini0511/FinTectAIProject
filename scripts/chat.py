"""Interactive REPL for the fintech support agent.

    python scripts/chat.py                      # interactive
    python scripts/chat.py "How much is a wire?" # one-shot
    python scripts/chat.py --semantic            # enable LLM-as-judge guardrail
    python scripts/chat.py --approve             # prompt before sensitive actions

Shows the answer plus the observability/safety sidecar: tool calls, token cost,
redacted PII, and any guardrail violations.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252 and choke on Unicode (em dashes, etc.).
# Force UTF-8 output so any character prints cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Make `src/` importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fintech_agent import FintechAgent  # noqa: E402
from fintech_agent.config import settings  # noqa: E402


def _human_approval(name: str, args: dict) -> bool:
    print(f"\n  ⚠  Sensitive action requested: {name}({args})")
    return input("     Approve? [y/N] ").strip().lower() == "y"


def show(result) -> None:
    print(f"\nNimbus> {result.answer}\n")
    if result.tool_calls:
        print("  tools:")
        for t in result.tool_calls:
            flag = " [sensitive]" if t.sensitive else ""
            ok = "" if t.approved else " DENIED"
            print(f"    - {t.name}{flag}{ok} {t.args}")
    print("\n  trace tree:")
    for line in result.trace_tree().splitlines():
        print("  " + line)
    c = result.cost
    print(f"\n  cost: ${c.get('cost_usd', 0):.5f} | {c.get('total_tokens', 0)} tokens | {c.get('api_calls', 0)} calls")
    if result.pii_redacted:
        print(f"  pii redacted from input: {result.pii_redacted}")
    if result.guardrail_violations:
        print(f"  guardrail: {result.guardrail_violations}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("message", nargs="*", help="One-shot message (omit for REPL).")
    parser.add_argument("--semantic", action="store_true", help="Enable semantic output guardrail.")
    parser.add_argument("--approve", action="store_true", help="Prompt before sensitive actions.")
    args = parser.parse_args()

    agent = FintechAgent(
        enable_semantic_guardrail=args.semantic,
        approve_sensitive=_human_approval if args.approve else None,
    )

    print(f"NimbusPay support agent - model={settings.model}, "
          f"tracing={'on' if settings.tracing_enabled else 'off'}")

    if args.message:
        show(agent.run(" ".join(args.message)))
        return

    print("Type a message ('quit' to exit). Try: 'What's the balance on acc_1001?'\n")
    print("Sample accounts: acc_1001 (cards card_8842, card_2207), acc_1002 (card_5519).\n")
    history: list = []  # conversation memory across turns
    while True:
        try:
            msg = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if msg.lower() in {"quit", "exit"}:
            break
        if msg:
            result = agent.run(msg, history=history)
            show(result)
            history.append({"role": "user", "content": result.user_message})
            history.append({"role": "assistant", "content": result.answer})


if __name__ == "__main__":
    main()
