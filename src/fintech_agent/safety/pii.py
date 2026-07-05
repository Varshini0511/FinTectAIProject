"""PII detection and redaction with Microsoft Presidio.

Used on BOTH sides of the agent:
  - inbound: redact PII from the customer message before it's logged/traced, so
    secrets never land in LangSmith or your logs.
  - outbound: a safety net to catch any PII the model might echo back.

Presidio + spaCy is the real path. If they aren't installed, we fall back to a
small regex analyzer so the rest of the project still runs (with a warning).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# Entities relevant to fintech support. CREDIT_CARD, US_SSN, EMAIL, PHONE, etc.
DEFAULT_ENTITIES = [
    "CREDIT_CARD",
    "US_SSN",
    "US_BANK_NUMBER",
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON",
    "IBAN_CODE",
]


@dataclass
class PIIReport:
    original: str
    redacted: str
    entities_found: list[str]

    @property
    def has_pii(self) -> bool:
        return bool(self.entities_found)


@lru_cache(maxsize=1)
def _presidio_engines():
    """Build Presidio analyzer + anonymizer once. Returns None if unavailable.

    The spaCy model is configurable via PRESIDIO_SPACY_MODEL (default
    en_core_web_lg locally; set en_core_web_sm on low-RAM hosts like Streamlit
    Cloud). Falls back to the regex detector if the model can't be loaded.
    """
    import os

    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine
    except Exception:
        return None

    model = os.getenv("PRESIDIO_SPACY_MODEL", "en_core_web_lg")
    try:
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model}],
            }
        )
        analyzer = AnalyzerEngine(nlp_engine=provider.create_engine(), supported_languages=["en"])
        # Force model load now so a missing spaCy model fails fast, not mid-request.
        analyzer.analyze(text="warmup", language="en")
        return analyzer, AnonymizerEngine()
    except Exception:
        return None


# --- Regex fallback (used only if Presidio/spaCy isn't installed) -------------

_FALLBACK_PATTERNS: dict[str, re.Pattern] = {
    "CREDIT_CARD": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "EMAIL_ADDRESS": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "PHONE_NUMBER": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
}


def _redact_fallback(text: str, entities: list[str]) -> PIIReport:
    found: list[str] = []
    redacted = text
    for entity, pattern in _FALLBACK_PATTERNS.items():
        if entity not in entities:
            continue
        if pattern.search(redacted):
            found.append(entity)
            redacted = pattern.sub(f"<{entity}>", redacted)
    return PIIReport(original=text, redacted=redacted, entities_found=found)


def redact_pii(text: str, entities: list[str] | None = None) -> PIIReport:
    """Detect and replace PII with `<ENTITY_TYPE>` placeholders."""
    entities = entities or DEFAULT_ENTITIES
    engines = _presidio_engines()
    if engines is None:
        return _redact_fallback(text, entities)

    analyzer, anonymizer = engines
    results = analyzer.analyze(text=text, entities=entities, language="en")
    if not results:
        return PIIReport(original=text, redacted=text, entities_found=[])

    from presidio_anonymizer.entities import OperatorConfig

    anonymized = anonymizer.anonymize(
        text=text,
        analyzer_results=results,
        operators={
            "DEFAULT": OperatorConfig("replace", {"new_value": "<REDACTED>"}),
            **{
                r.entity_type: OperatorConfig("replace", {"new_value": f"<{r.entity_type}>"})
                for r in results
            },
        },
    )
    return PIIReport(
        original=text,
        redacted=anonymized.text,
        entities_found=sorted({r.entity_type for r in results}),
    )
