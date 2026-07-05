"""The fintech support agent: a tool-use loop with safety + observability.

Runs on an OpenAI-compatible endpoint (Groq by default; xAI Grok or any other
OpenAI-compatible API via .env). A single `run(message)` call:
  1. redacts PII from the inbound message (so secrets never hit logs/traces),
  2. runs a chat-completions tool-use loop over the fintech tools,
  3. tracks token usage and cost from each response's `usage` object,
  4. applies output guardrails (regex always; semantic optional),
  5. returns an `AgentResult` with the answer, trace of tool calls, cost, and
     any guardrail/PII findings.

The whole thing is wrapped in `@traceable`, and the client is LangSmith-wrapped,
so a run shows up in LangSmith as one nested trace.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from langsmith import traceable
from openai import BadRequestError

# Llama models on Groq occasionally emit a tool call in tag syntax that Groq's
# parser rejects with `tool_use_failed`; we recover by parsing it out.
_FAILED_CALL = re.compile(r"<function=([A-Za-z_]\w*)>?\s*(\{.*?\})\s*</function>", re.DOTALL)

from .config import settings
from .observability import get_client
from .prompts import SYSTEM_PROMPT, UNSAFE_DEMO_PROMPT
from .safety import CostTracker, redact_pii, validate_output
from .tools import SENSITIVE_TOOLS, TOOLS, dispatch
from .tracing import Trace, render_tree


@dataclass
class ToolCall:
    name: str
    args: dict
    result: str
    sensitive: bool = False
    approved: bool = True


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    cost: dict = field(default_factory=dict)
    pii_redacted: list[str] = field(default_factory=list)
    guardrail_violations: list[str] = field(default_factory=list)
    retrieved_context: str = ""  # KB context, for faithfulness eval
    trace: list = field(default_factory=list)  # one span per stage (the trace tree)
    user_message: str = ""  # the redacted user text sent this turn (for conversation history)

    def __str__(self) -> str:
        return self.answer

    def trace_tree(self) -> str:
        """Render this run's spans as an indented trace tree (string)."""
        total = f"{self.cost.get('total_tokens', 0)} tok, ${self.cost.get('cost_usd', 0):.5f}"
        return render_tree(self.trace, total=total)


class FintechAgent:
    """Stateless per-call agent. Construct once, call `run()` per turn.

    Args:
        approve_sensitive: callback (name, args) -> bool gating block_card /
            file_dispute. Defaults to auto-approve. Wire this to a human-in-the-
            loop prompt in production.
        enable_semantic_guardrail: run the LLM-as-judge output check (extra call).
    """

    def __init__(self, *, approve_sensitive=None, enable_semantic_guardrail: bool = False,
                 unsafe_demo: bool = False):
        self.client = get_client()
        self.approve_sensitive = approve_sensitive or (lambda name, args: True)
        self.enable_semantic_guardrail = enable_semantic_guardrail
        # unsafe_demo swaps in a prompt with NO safety rules, so the model produces
        # violating answers you can watch the semantic guardrail catch. Demo only.
        self.unsafe_demo = unsafe_demo

    def _invoke(self, name: str, args: dict, tool_calls: list, retrieved: list) -> str:
        """Run one tool (with sensitive-action gating) and record it. Returns the result string."""
        sensitive = name in SENSITIVE_TOOLS
        approved = (not sensitive) or bool(self.approve_sensitive(name, args))
        if approved:
            result = dispatch(name, args)
        else:
            result = (
                f"DENIED: '{name}' requires human approval, which was not granted. "
                "Tell the customer this action needs confirmation from a human agent."
            )
        if name == "search_knowledge_base":
            retrieved.append(result)
        tool_calls.append(ToolCall(name=name, args=args, result=result, sensitive=sensitive, approved=approved))
        return result

    def _recover_failed_tool_call(self, exc: BadRequestError, messages: list, tool_calls: list, retrieved: list, trace=None) -> bool:
        """Handle Groq's `tool_use_failed`: parse the attempted call, run it, inject the result.

        Returns True if at least one tool was recovered and executed.
        """
        body = getattr(exc, "body", None) or {}
        err = body.get("error", body) if isinstance(body, dict) else {}
        if err.get("code") != "tool_use_failed":
            return False
        failed = err.get("failed_generation", "") or ""

        executed = []
        for name, raw_args in _FAILED_CALL.findall(failed):
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                continue
            if trace is not None:
                with trace.span(f"tool.{name}", input=args, recovered=True) as sp:
                    result = self._invoke(name, args, tool_calls, retrieved)
                    sp.data["output"] = (result or "")[:80]
            else:
                result = self._invoke(name, args, tool_calls, retrieved)
            executed.append(f"{name} -> {result}")
        if not executed:
            return False

        messages.append(
            {"role": "user", "content": "[tool results]\n" + "\n".join(executed) + "\n\nUse these to answer the customer."}
        )
        return True

    @traceable(name="agent.run", run_type="chain")
    def run(self, message: str, history: list | None = None) -> AgentResult:
        # `history` is prior [{role, content}] user/assistant turns. Passing it in
        # gives the agent CONVERSATION MEMORY — it can resolve follow-ups like a
        # bare "acc_1001" that refer back to an earlier question.
        # ===== 🔴 SET YOUR FIRST BREAKPOINT ON THE NEXT LINE, THEN PRESS F10 =====
        # STEP 0 — start an empty cost meter and a trace recorder.
        cost = CostTracker(model=settings.model)
        trace = Trace()  # records one span (with latency) per stage below

        # STEP 1 — PII REDACTION. F11 here to step INTO redact_pii (safety/pii.py),
        # or F10 to step over. Afterwards inspect `pii.original` vs `pii.redacted`.
        with trace.span("pii.redact") as sp:

            pii = redact_pii(message)
            user_text = pii.redacted  # everything below uses the MASKED text
            sp.data["entities"] = pii.entities_found

        system_prompt = UNSAFE_DEMO_PROMPT if self.unsafe_demo else SYSTEM_PROMPT
        # system prompt + prior turns (memory) + this turn's message
        messages = [{"role": "system", "content": system_prompt}]
        messages += list(history or [])
        messages.append({"role": "user", "content": user_text})
        tool_calls: list[ToolCall] = []
        retrieved_context_parts: list[str] = []
        answer = ""
        forced_no_tools = False  # set after recovering a malformed tool call

        # STEP 2 — THE AGENT LOOP. Each pass asks the model: answer, or call a tool?
        for _ in range(settings.max_tool_iterations):
            with trace.span("llm.call") as sp:  # one span per model round-trip
                try:
                    # F10 over this line, then inspect `msg` below:
                    #   msg.tool_calls present  -> model wants to run a tool (go to STEP 3)
                    #   msg.tool_calls is None   -> model gave the final answer (loop breaks)
                    resp = self.client.chat.completions.create(
                        model=settings.model,
                        max_tokens=settings.max_tokens,
                        temperature=0,
                        tools=TOOLS,
                        tool_choice="none" if forced_no_tools else "auto",
                        messages=messages,
                    )
                except BadRequestError as exc:
                    if self._recover_failed_tool_call(exc, messages, tool_calls, retrieved_context_parts, trace):
                        sp.data["decision"] = "recovered tool_use_failed"
                        forced_no_tools = True  # next call: answer using the injected results
                        continue
                    raise

                if resp.usage:
                    cost.add(resp.usage)  # 3. exact token/cost accounting
                    sp.data["tokens"] = resp.usage.total_tokens

                msg = resp.choices[0].message
                sp.data["decision"] = (
                    "final_answer" if not msg.tool_calls
                    else "calls: " + ", ".join(tc.function.name for tc in msg.tool_calls)
                )

            if not msg.tool_calls:
                answer = (msg.content or "").strip()
                break

            # Echo the assistant turn (with its tool_calls) back into history.
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )

            for tc in msg.tool_calls:
                name = tc.function.name          # e.g. "search_knowledge_base"
                try:
                    args = json.loads(tc.function.arguments or "{}")  # the model's chosen args
                except json.JSONDecodeError:
                    args = {}
                # STEP 3 — RUN THE TOOL. F11 here to step INTO _invoke, then into
                # dispatch() in tools.py. Inspect `name`, `args`, and `result`.
                with trace.span(f"tool.{name}", input=args) as sp:
                    result = self._invoke(name, args, tool_calls, retrieved_context_parts)
                    sp.data["output"] = (result or "")[:80]
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                # ...then the loop repeats: the model now sees `result` and usually answers.
        else:
            # loop exhausted without a final text answer
            if not answer:
                answer = "I wasn't able to complete that. Let me hand you to a human agent."

        retrieved_context = "\n\n".join(retrieved_context_parts)

        # STEP 4 — OUTPUT GUARDRAILS. F11 to step into validate_output
        # (safety/guardrails.py). Inspect `guard.violations` afterwards.
        with trace.span("guardrail.validate_output") as sp:
            guard = validate_output(
                answer,
                question=user_text,
                context=retrieved_context,
                semantic=self.enable_semantic_guardrail,
                client=self.client,
            )
            sp.data["violations"] = guard.violations

        # STEP 5 — bundle everything the UI/CLI shows. Inspect this return value.
        return AgentResult(
            answer=guard.output,
            tool_calls=tool_calls,
            cost=cost.summary(),
            pii_redacted=pii.entities_found,
            guardrail_violations=guard.violations,
            retrieved_context=retrieved_context,
            trace=trace.to_list(),
            user_message=user_text,
        )
