"""Build a LangSmith evaluation dataset.

Two sources, both in the spirit of "curate traces into a dataset":

1. seed_dataset()      — push the hand-written GOLDEN_SET (evals/dataset.py).
2. dataset_from_traces() — pull real runs from your LangSmith project, filtered
   to the ones you've curated (e.g. thumbs-down feedback, or a "golden" tag), and
   turn each into a dataset example. This is how you grow the eval set from
   production: triage bad traces in the UI, tag them, then materialize them here.

Run:  python -m evals.build_dataset --seed
      python -m evals.build_dataset --from-traces --tag golden --limit 50
"""

from __future__ import annotations

import argparse

from fintech_agent.config import settings

from .dataset import GOLDEN_SET

DATASET_NAME = "fintech-support-golden"


def _client():
    from langsmith import Client

    return Client()


def seed_dataset(name: str = DATASET_NAME) -> str:
    """Create (or reuse) a dataset and upload the golden examples."""
    client = _client()
    if client.has_dataset(dataset_name=name):
        ds = client.read_dataset(dataset_name=name)
    else:
        ds = client.create_dataset(dataset_name=name, description="Golden set for the fintech support agent.")

    existing = {ex.metadata.get("example_id") for ex in client.list_examples(dataset_id=ds.id)}
    created = 0
    for ex in GOLDEN_SET:
        if ex.id in existing:
            continue
        client.create_example(
            dataset_id=ds.id,
            inputs={"message": ex.message},
            outputs={"reference": ex.reference},
            metadata={
                "example_id": ex.id,
                "expects_tools": ex.expects_tools,
                "must_include": ex.must_include,
                "must_not_include": ex.must_not_include,
                "is_attack": ex.is_attack,
            },
        )
        created += 1
    print(f"Dataset '{name}': {created} new example(s), {len(existing)} already present.")
    return name


def dataset_from_traces(tag: str = "golden", limit: int = 50, name: str = DATASET_NAME + "-from-traces") -> str:
    """Materialize curated production traces into a dataset.

    Filters runs in the LangSmith project to top-level `agent.run` traces that you
    curated (here: tagged `golden`). Adjust the filter to match how you triage —
    e.g. `filter='and(eq(feedback_key, "correctness"), lt(feedback_score, 0.5))'`
    to collect the agent's failures for a regression set.
    """
    client = _client()
    runs = client.list_runs(
        project_name=settings.langsmith_project,
        filter=f'and(eq(name, "agent.run"), has(tags, "{tag}"))',
        limit=limit,
    )

    if client.has_dataset(dataset_name=name):
        ds = client.read_dataset(dataset_name=name)
    else:
        ds = client.create_dataset(dataset_name=name, description=f"Curated from traces tagged '{tag}'.")

    count = 0
    for run in runs:
        inputs = run.inputs or {}
        message = inputs.get("message") or inputs.get("args", [""])[0] if inputs else ""
        if not message:
            continue
        client.create_example(
            dataset_id=ds.id,
            inputs={"message": message},
            outputs={"reference": (run.outputs or {}).get("answer", "")},
            metadata={"source_run_id": str(run.id)},
        )
        count += 1
    print(f"Dataset '{name}': added {count} example(s) from traces tagged '{tag}'.")
    return name


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true", help="Upload the golden set.")
    parser.add_argument("--from-traces", action="store_true", help="Build from curated traces.")
    parser.add_argument("--tag", default="golden")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    if args.from_traces:
        dataset_from_traces(tag=args.tag, limit=args.limit)
    else:
        seed_dataset()
