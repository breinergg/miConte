"""Post-generation validation to prevent the LLM from introducing causal language."""

from __future__ import annotations

# Phrases that assert a causal relationship — prohibited by miconte-statistical-validation.
_CAUSAL_PATTERNS: tuple[str, ...] = (
    "causó",
    "causó ",
    "provocó",
    "es la razón",
    "es la causa",
    "debido a que",
    "por lo que causó",
    "generó el efecto",
    "tuvo como causa",
    "se debe a que",
    "was caused by",
    "caused the",
    "the reason for",
)


def contains_causal_language(text: str) -> bool:
    """Return True if *text* contains any prohibited causal assertion."""
    lower = text.lower()
    return any(pat in lower for pat in _CAUSAL_PATTERNS)
