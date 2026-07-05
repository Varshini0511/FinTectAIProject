"""Run the evaluation suite.

Two modes:

  Local (no LangSmith account needed):
      python -m evals.run_eval --local

  LangSmith experiment (compares versions in the dashboard):
      python -m evals.run_eval --langsmith --experiment v1-opus

The LangSmith mode uses `evaluate()`: it runs the agent over every example in the
dataset, scores each with our evaluators, and uploads an experiment you can diff
against another run (e.g. Opus vs Sonnet) in the UI.
"""

from __future__ import annotations

import argparse
import statistics

from openai import OpenAI

from fintech_agent import FintechAgent
from fintech_agent.config import settings


def _judge_client() -> OpenAI:
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url)

from . import evaluators
from .build_dataset import DATASET_NAME, seed_dataset
from .dataset import GOLDEN_SET, by_id


def run_local() -> None:
    agent = FintechAgent(enable_semantic_guardrail=False)
    judge = _judge_client()

    scores: dict[str, list[float]] = {}
    print(f"\nRunning {len(GOLDEN_SET)} examples on {settings.model}\n" + "=" * 72)
    for ex in GOLDEN_SET:
        result = agent.run(ex.message)
        row = []
        for fn in evaluators.ALL_EVALUATORS:
            ev = fn(ex, result, judge) if fn is evaluators.correctness_judge else fn(ex, result)
            if ev["score"] is not None:
                scores.setdefault(ev["key"], []).append(ev["score"])
                row.append(f"{ev['key']}={ev['score']:.2f}")
        print(f"[{ex.id:18}] {' '.join(row)}")
        print(f"    cost=${result.cost.get('cost_usd', 0):.5f} "
              f"tokens={result.cost.get('total_tokens', 0)} "
              f"pii={result.pii_redacted} guardrail={result.guardrail_violations}")

    print("=" * 72)
    for key, vals in scores.items():
        print(f"  mean {key:16} = {statistics.mean(vals):.3f}  (n={len(vals)})")
    print()


def run_langsmith(experiment: str | None) -> None:
    from langsmith import evaluate

    seed_dataset()  # ensure the dataset exists/upToDate
    agent = FintechAgent(enable_semantic_guardrail=False)
    judge = _judge_client()

    def target(inputs: dict) -> dict:
        result = agent.run(inputs["message"])
        return {
            "answer": result.answer,
            "tool_calls": [t.name for t in result.tool_calls],
            "cost_usd": result.cost.get("cost_usd", 0),
            "_result": result,  # passed through to evaluators below
        }

    # Adapt our (example, result) evaluators to LangSmith's (run, example) shape.
    def _adapt(fn):
        def _ls_eval(run, example):
            ex = by_id(example.metadata["example_id"])
            result = run.outputs["_result"]
            return fn(ex, result, judge) if fn is evaluators.correctness_judge else fn(ex, result)

        _ls_eval.__name__ = fn.__name__
        return _ls_eval

    evaluate(
        target,
        data=DATASET_NAME,
        evaluators=[_adapt(fn) for fn in evaluators.ALL_EVALUATORS],
        experiment_prefix=experiment or f"fintech-{settings.model}",
        metadata={"model": settings.model},
    )
    print(f"\nExperiment uploaded. Open LangSmith → datasets → '{DATASET_NAME}' to compare.\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Run offline, print a score table.")
    parser.add_argument("--langsmith", action="store_true", help="Run as a LangSmith experiment.")
    parser.add_argument("--experiment", default=None, help="Experiment name prefix.")
    args = parser.parse_args()

    if args.langsmith:
        run_langsmith(args.experiment)
    else:
        run_local()
