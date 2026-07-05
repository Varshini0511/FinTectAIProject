"""DeepEval metrics — faithfulness, answer relevancy, hallucination.

DeepEval defaults to OpenAI as its judge. We point it at our Groq model with a
thin `DeepEvalBaseLLM` adapter so the whole project uses one provider.

  - Faithfulness     : does the answer stay grounded in the retrieved KB context?
  - Answer Relevancy : does the answer actually address the question?
  - Hallucination    : does the answer contradict the provided context?

Run:  python -m evals.deepeval_metrics
"""

from __future__ import annotations

from openai import OpenAI
from deepeval import evaluate as deepeval_evaluate
from deepeval.metrics import (
    AnswerRelevancyMetric,
    FaithfulnessMetric,
    HallucinationMetric,
)
from deepeval.models.base_model import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase

from fintech_agent import FintechAgent
from fintech_agent.config import settings

from .dataset import GOLDEN_SET


class GroqJudge(DeepEvalBaseLLM):
    """Adapter so DeepEval grades with our Groq model instead of OpenAI."""

    def __init__(self, model: str | None = None):
        self.model = model or settings.judge_model
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)

    def load_model(self):
        return self.client

    def generate(self, prompt: str, *args, **kwargs) -> str:
        # DeepEval may pass a pydantic schema as the 2nd arg for structured output.
        schema = args[0] if args else kwargs.get("schema")
        resp = self.client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a meticulous evaluation judge. Follow the output format exactly."},
                {"role": "user", "content": prompt},
            ],
        )
        text = resp.choices[0].message.content or ""
        if schema is not None:
            # Best-effort: coerce the JSON-ish reply into the requested schema.
            import json
            import re

            match = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(match.group(0)) if match else {}
            return schema(**data)
        return text

    async def a_generate(self, prompt: str, *args, **kwargs):
        return self.generate(prompt, *args, **kwargs)

    def get_model_name(self) -> str:
        return self.model


def build_test_cases(limit: int | None = None) -> list[LLMTestCase]:
    """Run the agent on KB-grounded examples and wrap each as an LLMTestCase."""
    agent = FintechAgent()
    cases: list[LLMTestCase] = []
    # Only examples that actually retrieve context make sense for faithfulness.
    examples = [e for e in GOLDEN_SET if "search_knowledge_base" in e.expects_tools]
    for ex in examples[: limit or len(examples)]:
        result = agent.run(ex.message)
        context = [result.retrieved_context] if result.retrieved_context else ["(no context retrieved)"]
        cases.append(
            LLMTestCase(
                input=ex.message,
                actual_output=result.answer,
                retrieval_context=context,  # for Faithfulness / AnswerRelevancy
                context=context,            # for Hallucination
            )
        )
    return cases


def main() -> None:
    judge = GroqJudge()
    metrics = [
        FaithfulnessMetric(threshold=0.7, model=judge),
        AnswerRelevancyMetric(threshold=0.7, model=judge),
        HallucinationMetric(threshold=0.3, model=judge),  # lower is better; threshold is a max
    ]
    cases = build_test_cases()
    print(f"Evaluating {len(cases)} test case(s) with DeepEval judge={judge.get_model_name()}\n")
    deepeval_evaluate(test_cases=cases, metrics=metrics)


if __name__ == "__main__":
    main()
