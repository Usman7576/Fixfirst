"""Masks secrets in code snippets before they are stored or sent to an LLM provider."""

import math
import re
from collections import Counter

REDACTED = "«redacted»"

_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),  # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),  # Stripe
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),  # Google API key
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),  # JWT
]

# key = "value" where the key name suggests a credential.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<key>[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|private[_-]?key|credential)[\w.-]*)
    (?P<sep>\s*[:=]\s*|\s*=>\s*)
    (?P<quote>["'`])(?P<value>[^"'`\n]{6,})(?P=quote)
    """
)

# Long opaque strings that look random enough to be keys.
_OPAQUE = re.compile(r"""(?P<quote>["'])(?P<value>[A-Za-z0-9+/=_-]{32,})(?P=quote)""")
_MIN_ENTROPY = 4.0


def _entropy(value: str) -> float:
    counts = Counter(value)
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def redact_secrets(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(REDACTED, text)
    text = _ASSIGNMENT.sub(
        lambda m: f"{m['key']}{m['sep']}{m['quote']}{REDACTED}{m['quote']}", text
    )
    return _OPAQUE.sub(
        lambda m: (
            f"{m['quote']}{REDACTED}{m['quote']}"
            if _entropy(m["value"]) >= _MIN_ENTROPY
            else m.group(0)
        ),
        text,
    )
