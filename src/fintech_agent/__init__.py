"""Production-ready fintech support agent.

Public surface:
    from fintech_agent import FintechAgent, AgentResult
"""

from .agent import AgentResult, FintechAgent

__all__ = ["FintechAgent", "AgentResult"]
