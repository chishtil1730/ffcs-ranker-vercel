"""Name normalization and initial-aware token matching."""
from __future__ import annotations

import re
from functools import lru_cache
from itertools import permutations
from typing import Optional

from unidecode import unidecode

TITLES = {"dr", "prof", "professor", "mr", "mrs", "ms"}
_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


@lru_cache(maxsize=4096)
def normalize_name(name: str) -> str:
    """Lowercase, strip titles/punctuation, collapse whitespace."""
    if not name:
        return ""
    text = unidecode(str(name)).lower()
    text = _PUNCT_RE.sub(" ", text)
    tokens = [t for t in text.split() if t not in TITLES]
    return _SPACE_RE.sub(" ", " ".join(tokens)).strip()


@lru_cache(maxsize=4096)
def tokens_of(name: str) -> tuple[str, ...]:
    return tuple(normalize_name(name).split())


def token_sorted(name: str) -> str:
    return " ".join(sorted(tokens_of(name)))


def _token_or_initial_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) == 1:
        return b.startswith(a)
    if len(b) == 1:
        return a.startswith(b)
    return False


def initials_match_score(name_a: str, name_b: str) -> Optional[int]:
    """Return a confidence score (0-99) if names match allowing initials,
    trying all token permutations (cheap for short name lists). None if no match."""
    ta, tb = tokens_of(name_a), tokens_of(name_b)
    if len(ta) != len(tb) or not ta:
        return None
    best_exact = 0
    for perm in permutations(tb):
        if all(_token_or_initial_equal(x, y) for x, y in zip(ta, perm)):
            exact = sum(1 for x, y in zip(ta, perm) if x == y)
            best_exact = max(best_exact, exact)
    if best_exact == 0:
        return None
    # all positions matched (exact or initial); scale score by how many were exact
    return 90 + int(9 * (best_exact / len(ta)))  # 90-99
