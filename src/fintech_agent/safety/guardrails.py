"""Output guardrails: regex, schema, and semantic validators.

These mirror the three Guardrails-AI validator families the curriculum calls for.
We implement them directly so the project runs without pulling Guardrails Hub
validators (which need network/auth to install). The mapping to Guardrails AI:

  regex    -> guardrails `RegexMatch` / a custom @register_validator
  schema   -> a Pydantic/JSON-schema `Guard` over structured output
  semantic -> an LLM-as-judge validator (e.g. `LlmRagEvaluator` / custom)

To use the real Guardrails AI runtime instead, wrap these in a Guard:

    from guardrails import Guard
    guard = Guard().use_many(RegexMatch(...), ...)
    outcome = guard.validate(text)

`validate_output` returns a structured result; the agent decides whether to block,
fix, or pass the response through.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --- 1. Regex validators: hard-block sensitive patterns in OUTPUT -------------

# The model must never emit these. Last-4 references are fine; full numbers aren't.
_FULL_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CVV_NEARBY = re.compile(r"\b(?:cvv|cvc|security code)\b.{0,12}\b\d{3,4}\b", re.IGNORECASE)


@dataclass
class GuardrailResult:
    passed: bool
    output: str  # possibly redacted/fixed
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "violations": self.violations}


def _regex_checks(text: str) -> tuple[str, list[str]]:
    violations: list[str] = []
    fixed = text
    if _FULL_CARD.search(fixed):
        violations.append("regex:full_card_number_in_output")
        fixed = _FULL_CARD.sub("<CARD_REDACTED>", fixed)
    if _SSN.search(fixed):
        violations.append("regex:ssn_in_output")
        fixed = _SSN.sub("<SSN_REDACTED>", fixed)
    if _CVV_NEARBY.search(fixed):
        violations.append("regex:cvv_in_output")
    return fixed, violations


# --- 2. Schema validator: validate structured output against a JSON schema ----


def validate_schema(payload: str | dict, schema: dict) -> tuple[bool, list[str]]:
    """Minimal JSON-schema check (type + required). Returns (ok, violations).

    Demonstrates the 'schema validator' family for when a tool/route must return
    structured JSON. For full JSON Schema support, plug in `jsonschema.validate`.
    """
    violations: list[str] = []
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except json.JSONDecodeError as exc:
        return False, [f"schema:invalid_json:{exc.msg}"]

    if schema.get("type") == "object" and not isinstance(data, dict):
        return False, ["schema:expected_object"]

    for key in schema.get("required", []):
        if key not in data:
            violations.append(f"schema:missing_required:{key}")

    props = schema.get("properties", {})
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list}
    for key, spec in props.items():
        if key in data and (expected := type_map.get(spec.get("type"))):
            if not isinstance(data[key], expected):
                violations.append(f"schema:wrong_type:{key}")

    return not violations, violations


# --- 3. Semantic validator: LLM-as-judge for policy/grounding ----------------

_SEMANTIC_PROMPT = """\
You are a compliance guardrail for a bank's support agent. Judge the agent's \
reply against this customer message and policy context.

Customer: {question}

Policy context the agent had:
{context}

Agent reply:
{answer}

Flag a violation if the reply:
- states a fee/limit/timeline that contradicts or isn't supported by the context
  (hallucinated policy), OR
- gives personalized financial/investment advice, OR
- asks for a full card number, PIN, CVV, password, or one-time passcode.

Respond with ONLY a JSON object:
{{"violation": true|false, "reasons": ["..."]}}\
"""


def validate_semantic(question: str, answer: str, context: str, client=None, model: str | None = None) -> tuple[bool, list[str]]:
    """LLM-as-judge semantic guardrail. Returns (ok, violations).

    Requires an OpenAI-compatible client; if none is given one is created. Network call.
    """
    from ..config import settings

    if client is None:
        from openai import OpenAI

        client = OpenAI(api_key=settings.api_key, base_url=settings.base_url)
    model = model or settings.judge_model

    resp = client.chat.completions.create(
        model=model,
        max_tokens=512,
        temperature=0,
        messages=[
            {"role": "system", "content": "You are a precise compliance classifier. Output JSON only."},
            {
                "role": "user",
                "content": _SEMANTIC_PROMPT.format(question=question, context=context or "(none)", answer=answer),
            },
        ],
    )
    text = resp.choices[0].message.content or "{}"
    try:
        verdict = json.loads(text)
    except json.JSONDecodeError:
        return True, []  # fail open on a malformed judge response; log upstream
    if verdict.get("violation"):
        return False, [f"semantic:{r}" for r in verdict.get("reasons", ["policy_violation"])]
    return True, []


# --- Orchestrator -------------------------------------------------------------


def validate_output(
    answer: str,
    *,
    question: str = "",
    context: str = "",
    semantic: bool = False,
    client=None,
) -> GuardrailResult:
    """Run regex (always) + optional semantic checks over an agent reply.

    Regex violations are auto-fixed (redacted) but still reported. Semantic
    violations block (passed=False) so the caller can regenerate or escalate.
    """
    fixed, violations = _regex_checks(answer)

    if semantic:
        ok, sem_violations = validate_semantic(question, fixed, context, client=client)
        violations += sem_violations

    blocking = [v for v in violations if v.startswith("semantic:") or v.endswith("cvv_in_output")]
    return GuardrailResult(passed=not blocking, output=fixed, violations=violations)
